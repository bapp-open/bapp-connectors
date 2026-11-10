"""Family-generic checks on the ``@ai_method`` markers of provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
credentials. Each family keeps its own reviewed lists in ``test_ai_marking_guard_<family>.py``
and runs the ``check_*`` functions below for every provider of the family.

Every check takes ``(family, provider, reviewed, reviewed_extra)`` (some take more, keyword
only): ``reviewed`` is the family's ``REVIEWED_READ_METHODS`` (provider -> set of method names),
``reviewed_extra`` its ``REVIEWED_READ_EXTRA`` ((provider, method) -> {key: shape}).
Adapters are looked up by ``(family, provider)``: provider names repeat across families.
"""

from __future__ import annotations

import contextlib
import functools
import importlib
import inspect
import pkgutil
import re
import socket
import typing
from collections.abc import Iterator, Mapping

from bapp_connectors.core.ai import AI_ATTR, FORBIDDEN_EXTRA_KEYS, ai_methods, key_allowed
from bapp_connectors.core.registry import registry

Reviewed = Mapping[str, set[str]]
ReviewedExtra = Mapping[tuple[str, str], Mapping[str, str]]

# Keys no allow-list may ever contain: PHP routing / method override, response wrappers,
# query-string credentials.
ROUTING_OR_AUTH_KEYS = frozenset(
    {
        "_method",
        "rest_route",
        "_jsonp",
        "_envelope",
        "consumer_key",
        "consumer_secret",
        "oauth_consumer_key",
        "oauth_signature",
        "ps_method",
        "url",
        "ws_key",
        "output_format",
        "io_format",
        "schema",
    }
)

LAZY_RETURN = re.compile(
    r"\b(Iterator|Iterable|Generator|AsyncIterator|AsyncIterable|AsyncGenerator|Awaitable|Coroutine)\b"
)
BYTES_RETURN = re.compile(r"\b(bytes|bytearray|Response)\b")


# ── providers / adapters ──


def family_providers(family: str) -> list[str]:
    """Import every provider package of ``family`` and return the registered names, sorted."""
    pkg = importlib.import_module(f"bapp_connectors.providers.{family}")
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.ispkg:
            importlib.import_module(f"{pkg.__name__}.{mod.name}")
    return sorted(m.name for m in registry.list_providers(family=family))


def _dummy_credentials(manifest) -> dict:
    creds = {}
    for f in manifest.auth.required_fields:
        if f.choices:
            creds[f.name] = f.choices[0]
        elif f.default:
            creds[f.name] = f.default
        elif f.role == "endpoint" or any(part in f.name for part in ("url", "domain", "site")):
            creds[f.name] = "https://shop.example.com"
        elif f.name.endswith("_number"):  # parsed as int in __init__ (GLS client_number)
            creds[f.name] = "1"
        else:
            creds[f.name] = "dummy"
    return creds


@contextlib.contextmanager
def no_network() -> Iterator[None]:
    """Fail loudly if anything opens a connection (an adapter must not call out in __init__)."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"network access while building an adapter: {args!r}")

    saved = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo = saved


@functools.cache
def adapter(family: str, provider: str):
    """The adapter built with dummy credentials, with the network blocked."""
    manifest = registry.get_manifest(family, provider)
    with no_network():
        return registry.create_adapter(family, provider, credentials=_dummy_credentials(manifest))


def client_cls(family: str, provider: str) -> type:
    return type(adapter(family, provider).get_ai_client())


def read_methods(family: str, provider: str) -> Iterator[tuple[str, typing.Callable, typing.Any]]:
    """(name, function, AiMethodInfo) of every ``read``-marked method of the provider's client."""
    cls = client_cls(family, provider)
    for name, info in ai_methods(cls).items():
        if info.kind == "read":
            yield name, getattr(cls, name), info


def _dict_typed(annotation) -> bool:
    text = annotation if isinstance(annotation, str) else repr(annotation)
    return bool(re.search(r"\b(dict|Dict|Mapping)\b", text))


# ── family-level check ──


def check_family_coverage(family: str, reviewed: Reviewed, not_marked: Mapping[str, str]) -> None:
    """Every registered provider is reviewed or explicitly left unmarked (with a reason), never both;
    a provider left unmarked really has no read marks."""
    providers = set(family_providers(family))
    missing = providers - set(reviewed) - set(not_marked)
    assert not missing, f"{family}: providers neither reviewed nor in NOT_MARKED: {sorted(missing)}"
    both = set(reviewed) & set(not_marked)
    assert not both, f"{family}: providers both reviewed and NOT_MARKED: {sorted(both)}"
    unknown = (set(reviewed) | set(not_marked)) - providers
    assert not unknown, f"{family}: listed providers that are not registered: {sorted(unknown)}"
    for provider, reason in not_marked.items():
        assert reason and reason.strip(), f"{family}.{provider}: NOT_MARKED needs a reason"
        client = adapter(family, provider).get_ai_client()
        reads = [n for n, i in ai_methods(client).items() if i.kind == "read"] if client is not None else []
        assert not reads, f"{family}.{provider}: in NOT_MARKED but marks {reads} read"


# ── per-provider checks: (family, provider, reviewed, reviewed_extra) ──


def check_exposes_ai_client(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    """Built with fake credentials (no network), the adapter hands out a client with marks."""
    client = adapter(family, provider).get_ai_client()
    assert client is not None, f"{family}.{provider}: adapter has no AI client"
    assert ai_methods(client), f"{family}.{provider}: client has no @ai_method marks"
    assert provider in reviewed, f"{family}.{provider}: provider missing from the reviewed list"


def check_read_methods_reviewed(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    marked = {name for name, _fn, _info in read_methods(family, provider)}
    assert marked == reviewed[provider], f"{family}.{provider}: read marks differ from the reviewed list"


def check_annotated_params(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    for name, fn, _info in read_methods(family, provider):
        for param in list(inspect.signature(fn).parameters.values())[1:]:
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            assert param.annotation is not param.empty, f"{family}.{provider}.{name}: {param.name} has no annotation"


def check_var_kwargs_extra(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    """Read methods taking **kwargs declare exactly the reviewed extra keys (none if they only
    forward them to the HTTP layer); a method without **kwargs declares none."""
    for name, fn, info in read_methods(family, provider):
        params = inspect.signature(fn).parameters.values()
        has_var_kwargs = any(p.kind is p.VAR_KEYWORD for p in params)
        expected = dict(reviewed_extra.get((provider, name), {}))
        if not has_var_kwargs:
            assert not expected, f"{family}.{provider}.{name}: extra declared but the method takes no **kwargs"
        assert dict(info.extra) == expected, f"{family}.{provider}.{name}: extra differs from the reviewed one"
        assert not set(info.extra) & FORBIDDEN_EXTRA_KEYS


def check_no_bytes_return(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    """No marked method (read or write) returns bytes or a raw response."""
    cls = client_cls(family, provider)
    for name, info in ai_methods(cls).items():
        returns = inspect.signature(getattr(cls, name)).return_annotation
        text = returns if isinstance(returns, str) else getattr(returns, "__name__", str(returns))
        assert not BYTES_RETURN.search(text), f"{family}.{provider}.{name} ({info.kind}) returns {text}"


def check_materialised_data(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    """BAPP refuses lazy results (generators, iterators, awaitables): a read returns its data."""
    for name, fn, _info in read_methods(family, provider):
        where = f"{family}.{provider}.{name}"
        assert not inspect.isgeneratorfunction(fn) and not inspect.iscoroutinefunction(fn), where
        assert not inspect.isasyncgenfunction(fn), where
        returns = inspect.signature(fn).return_annotation
        assert returns is not inspect.Signature.empty, f"{where}: no return annotation"
        text = returns if isinstance(returns, str) else str(returns)
        assert not LAZY_RETURN.search(text), f"{where} returns {text}"


def check_free_text_reviewed(
    family: str,
    provider: str,
    reviewed: Reviewed,
    reviewed_extra: ReviewedExtra,
    *,
    free_text: set[tuple[str, str, str]] = frozenset(),
) -> None:
    """Params annotated ``free_text`` (BAPP skips its path-safety check on them) are exactly the
    reviewed (provider, method, param) triples; each must only reach a query string or a body."""
    cls = client_cls(family, provider)
    found = set()
    for name in ai_methods(cls):
        for param in inspect.signature(getattr(cls, name)).parameters.values():
            ann = param.annotation
            if "free_text" in (ann if isinstance(ann, str) else repr(ann)):
                found.add((provider, name, param.name))
    assert found == {t for t in free_text if t[0] == provider}, f"{family}.{provider}: free_text params differ"


def check_plain_methods_only(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    """`ai_methods` skips a mark put above @staticmethod/@classmethod; none may exist."""
    cls = client_cls(family, provider)
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if isinstance(value, (staticmethod, classmethod)):
                where = f"{family}.{provider}: {klass.__name__}.{name}"
                assert not hasattr(value, AI_ATTR), f"{where} mark is ignored"
                assert not hasattr(value.__func__, AI_ATTR), f"{where} is not a method"


def check_annotations_resolve(family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra) -> None:
    """BAPP builds the tool schema from the type hints; a TYPE_CHECKING-only import breaks it."""
    cls = client_cls(family, provider)
    for name in ai_methods(cls):
        typing.get_type_hints(getattr(cls, name), include_extras=True)


def check_dict_params_have_allowed_keys(
    family: str, provider: str, reviewed: Reviewed, reviewed_extra: ReviewedExtra
) -> None:
    """Every 'flat' extra and every dict-typed named param of a read has an allow-list."""
    for name, fn, info in read_methods(family, provider):
        where = f"{family}.{provider}.{name}"
        for key, shape in info.extra.items():
            if shape == "flat":
                assert info.allowed_keys.get(key), f"{where}: flat extra {key!r} has no allowed_keys"
        for param in list(inspect.signature(fn).parameters.values())[1:]:
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            if _dict_typed(param.annotation):
                assert info.allowed_keys.get(param.name), f"{where}: dict param {param.name!r} unlisted"


def check_allowed_keys_safe(
    family: str,
    provider: str,
    reviewed: Reviewed,
    reviewed_extra: ReviewedExtra,
    *,
    extra_blocked: frozenset[str] | set[str] = frozenset(),
) -> None:
    """No allow-list admits a routing/auth key (``ROUTING_OR_AUTH_KEYS`` plus ``extra_blocked``)
    or a transport key (``FORBIDDEN_EXTRA_KEYS``)."""
    blocked = ROUTING_OR_AUTH_KEYS | FORBIDDEN_EXTRA_KEYS | set(extra_blocked)
    for name, _fn, info in read_methods(family, provider):
        for arg, patterns in info.allowed_keys.items():
            for key in blocked:
                assert not key_allowed(key, patterns), f"{family}.{provider}.{name}.{arg} allows {key!r}"


# The per-provider checks with the plain 4-argument signature, for a family file to run them all.
GENERIC_CHECKS = (
    check_exposes_ai_client,
    check_read_methods_reviewed,
    check_annotated_params,
    check_var_kwargs_extra,
    check_no_bytes_return,
    check_materialised_data,
    check_free_text_reviewed,
    check_plain_methods_only,
    check_annotations_resolve,
    check_dict_params_have_allowed_keys,
    check_allowed_keys_safe,
)
