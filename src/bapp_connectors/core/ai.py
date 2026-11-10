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
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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


def ai_method(kind: AiKind, description: str, *, extra: Mapping[str, AiExtraShape] | None = None) -> Callable[[F], F]:
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
    info = AiMethodInfo(kind=kind, description=description, extra=MappingProxyType(extra_items))

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
