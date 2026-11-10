"""Tests for the ``ai_method`` marker and ``ai_methods`` discovery."""

from __future__ import annotations

import dataclasses

import pytest

from bapp_connectors.core.ai import AiMethodInfo, ai_method, ai_methods
from bapp_connectors.core.ports.base import BasePort


def test_decorator_keeps_behaviour_and_sets_info():
    def get_order(order_id: int) -> dict:
        return {"id": order_id}

    decorated = ai_method("read", "Fetch one order by id.", extra={"params": "flat"})(get_order)

    assert decorated is get_order
    assert decorated(7) == {"id": 7}
    info = decorated.__bapp_ai__
    assert isinstance(info, AiMethodInfo)
    assert info.kind == "read"
    assert info.description == "Fetch one order by id."
    assert dict(info.extra) == {"params": "flat"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.kind = "write"


def test_extra_defaults_to_empty_and_is_read_only():
    @ai_method("write", "Acknowledge an order.")
    def ack(order_id: int) -> None:
        return None

    assert dict(ack.__bapp_ai__.extra) == {}

    source = {"limit": "scalar"}

    @ai_method("read", "List.", extra=source)
    def listing(**kwargs):
        return kwargs

    source["proxies"] = "flat"  # mutating the caller's dict must not leak in
    assert dict(listing.__bapp_ai__.extra) == {"limit": "scalar"}
    with pytest.raises(TypeError):
        listing.__bapp_ai__.extra["headers"] = "flat"


def test_invalid_kind_or_empty_description_raises():
    with pytest.raises(ValueError):
        ai_method("delete", "Nope.")
    with pytest.raises(ValueError):
        ai_method("read", "")
    with pytest.raises(ValueError):
        ai_method("read", "   ")
    with pytest.raises(ValueError):
        ai_method("read", "Bad shape.", extra={"params": "nested"})


@pytest.mark.parametrize(
    "key",
    [
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
    ],
)
def test_forbidden_extra_key_raises(key):
    with pytest.raises(ValueError):
        ai_method("read", "List.", extra={key: "flat"})


def test_ai_methods_includes_inherited_skips_private_and_unmarked():
    class BaseClient:
        @ai_method("read", "List orders.")
        def get_orders(self, page: int = 1):
            return []

        @ai_method("read", "Private helper.")
        def _internal(self):
            return None

        def unmarked(self):
            return None

    class ChildClient(BaseClient):
        @ai_method("write", "Acknowledge an order.")
        def order_acknowledge(self, order_id: int):
            return None

    class OverridingClient(ChildClient):
        def get_orders(self, page: int = 1):  # override drops the marker
            return []

    for target in (ChildClient, ChildClient()):
        found = ai_methods(target)
        assert set(found) == {"get_orders", "order_acknowledge"}
        assert found["get_orders"].kind == "read"
        assert found["order_acknowledge"].kind == "write"

    assert set(ai_methods(OverridingClient())) == {"order_acknowledge"}
    assert ai_methods(None) == {}


def test_base_port_get_ai_client_defaults_to_client_attr():
    class Adapter(BasePort):
        def validate_credentials(self) -> bool:
            return True

        def test_connection(self):
            return None

    adapter = Adapter()
    assert adapter.get_ai_client() is None

    sentinel = object()
    adapter.client = sentinel
    assert adapter.get_ai_client() is sentinel
