"""
Marker for provider client methods an AI agent may call.

A client method decorated with ``@ai_method('read', ...)`` only reads data at the
destination; ``@ai_method('write', ...)`` changes it. Unmarked methods are never
offered to an agent.

Contract relied on by consumers that do NOT import this module (the BAPP MCP
server): the decorated function carries ``__bapp_ai__``, an object with
``kind`` ('read' | 'write'), ``description`` (str) and ``extra`` (a mapping of
accepted ``**kwargs`` key -> 'scalar' | 'flat'). 'scalar' is one str/int/float/bool
value; 'flat' is a flat dict whose values are str/int/float/bool.

``allowed_keys`` (a mapping of argument name -> tuple of key patterns) lists the keys a
'flat' extra or a dict-typed named parameter may carry. A key passes when it equals a
pattern, or when a pattern ends with ``[`` and the key starts with it (``'filter['``
allows ``'filter[id]'``). Every 'flat' extra must have a non-empty entry; any key that
matches no pattern is refused by the consumer. Routing or authentication keys are never
listed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, TypeVar

AiKind = Literal["read", "write"]
AiExtraShape = Literal["scalar", "flat"]

AI_ATTR = "__bapp_ai__"

VALID_KINDS: frozenset[str] = frozenset({"read", "write"})
VALID_EXTRA_SHAPES: frozenset[str] = frozenset({"scalar", "flat"})

# Keys that ``ResilientHttpClient.call`` / ``requests`` would honour and that would let a
# caller redirect the request or its credentials. Never accepted as extra, whatever a client declares.
FORBIDDEN_EXTRA_KEYS: frozenset[str] = frozenset(
    {
        "proxies",
        "verify",
        "headers",
        "auth",
        "cookies",
        "allow_redirects",
        "timeout",
        "stream",
        "cert",
        "files",
        "hooks",
        "direct_response",
    }
)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class AiMethodInfo:
    kind: AiKind
    description: str
    extra: Mapping[str, AiExtraShape] = field(default_factory=lambda: MappingProxyType({}))
    allowed_keys: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))


def ai_method(
    kind: AiKind,
    description: str,
    *,
    extra: Mapping[str, AiExtraShape] | None = None,
    allowed_keys: Mapping[str, Iterable[str]] | None = None,
) -> Callable[[F], F]:
    """Mark a client method as callable by an AI agent. Behaviour is unchanged."""
    if kind not in VALID_KINDS:
        raise ValueError(f"ai_method kind must be 'read' or 'write', got {kind!r}")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("ai_method description must be a non-empty string")
    extra_items = dict(extra or {})
    for key, shape in extra_items.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"ai_method extra key must be a non-empty string, got {key!r}")
        if key in FORBIDDEN_EXTRA_KEYS:
            raise ValueError(f"ai_method extra key {key!r} is forbidden")
        if shape not in VALID_EXTRA_SHAPES:
            raise ValueError(f"ai_method extra {key!r} shape must be 'scalar' or 'flat', got {shape!r}")
    allowed: dict[str, tuple[str, ...]] = {}
    for arg, patterns in (allowed_keys or {}).items():
        if not isinstance(arg, str) or not arg:
            raise ValueError(f"ai_method allowed_keys argument must be a non-empty string, got {arg!r}")
        if isinstance(patterns, str):
            raise ValueError(f"ai_method allowed_keys[{arg!r}] must be a sequence of keys, not a string")
        items = tuple(patterns)
        if not items or not all(isinstance(k, str) and k for k in items):
            raise ValueError(f"ai_method allowed_keys[{arg!r}] must be non-empty strings")
        allowed[arg] = items
    for key, shape in extra_items.items():
        if shape == "flat" and key not in allowed:
            raise ValueError(f"ai_method 'flat' extra {key!r} needs an allowed_keys entry")
    info = AiMethodInfo(
        kind=kind,
        description=description,
        extra=MappingProxyType(extra_items),
        allowed_keys=MappingProxyType(allowed),
    )

    def decorator(fn: F) -> F:
        setattr(fn, AI_ATTR, info)
        return fn

    return decorator


def ai_methods(client_or_cls: Any) -> dict[str, AiMethodInfo]:
    """Marked public methods of a client instance or class, inherited ones included.

    The most derived definition of a name wins: overriding a marked method without
    re-marking it removes it from the result.
    """
    if client_or_cls is None:
        return {}
    cls = client_or_cls if isinstance(client_or_cls, type) else type(client_or_cls)
    found: dict[str, AiMethodInfo] = {}
    seen: set[str] = set()
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if name in seen:
                continue
            seen.add(name)
            if name.startswith("_"):
                continue
            func = getattr(value, "__func__", value)  # staticmethod / classmethod
            info = getattr(func, AI_ATTR, None)
            if isinstance(info, AiMethodInfo) and callable(func):
                found[name] = info
    return found


def _php_query_name(key: str) -> str:
    """The name PHP files a query key under in ``$_GET``: leading spaces dropped, the part
    before an array bracket kept, and spaces, dots and a stray ``[`` turned into ``_``."""
    name = key.lstrip(" ")
    bracket = name.find("[")
    if bracket > 0 and "]" in name[bracket:]:
        name = name[:bracket]
    return name.replace(" ", "_").replace(".", "_").replace("[", "_")


def key_allowed(key: str, patterns: Iterable[str]) -> bool:
    """Whether a dict key passes an ``allowed_keys`` entry (exact, or prefix ending in ``[``)."""
    return any(key == p or (p.endswith("[") and key.startswith(p)) for p in patterns)


def drop_query_overrides(params: Any, names: Iterable[str], prefixes: Iterable[str] = ()) -> Any:
    """Remove routing, method-override and auth keys from a GET's query params.

    PHP backends read some query keys before routing: WordPress ``_method`` and ``rest_route``,
    PrestaShop ``ps_method`` and ``url`` (the dispatcher's resource). Sent on a read, they move the
    credentialed request to another verb or resource. Keys are compared as PHP files them in
    ``$_GET`` (``_method``, ``.method``, `` _method``, ``_method[]`` are the same key), case-folded.
    Anything that is not a dict is returned unchanged.
    """
    if not isinstance(params, dict):
        return params
    drop = {n.lower() for n in names}
    starts = tuple(p.lower() for p in prefixes)

    def blocked(key: Any) -> bool:
        if not isinstance(key, str):
            return False
        name = _php_query_name(key).lower()
        return name in drop or (bool(starts) and name.startswith(starts))

    return {k: v for k, v in params.items() if not blocked(k)}


def drop_method_override(params: Any, override_name: str) -> Any:
    """Remove one PHP method-override query key (WordPress ``_method``, PrestaShop ``ps_method``)."""
    return drop_query_overrides(params, (override_name,))


# Query keys a WooCommerce GET never sends on a caller's behalf: method override, REST
# re-routing, response wrappers, and the query-string credentials the client adds itself.
WOOCOMMERCE_BLOCKED_QUERY = ("_method", "rest_route", "_jsonp", "_envelope")
WOOCOMMERCE_BLOCKED_PREFIXES = ("consumer_", "oauth_")
# PrestaShop: method override, the dispatcher's resource (`url`), the key and output switches.
PRESTASHOP_BLOCKED_QUERY = ("ps_method", "url", "ws_key", "output_format", "io_format", "schema")
