"""Self-tests of the family-generic AI guard (tests/core/ai_guard.py).

No ``from __future__ import annotations`` here on purpose: the fake clients need evaluated
annotations as well as string ones.
"""

import socket
from typing import Optional

import pytest
import requests

from bapp_connectors.core.ai import ai_method
from tests.core import ai_guard


class _BinaryClient:
    @ai_method("read", "Tuple.")
    def as_tuple(self) -> tuple[bytes, str]:
        return b"", ""

    @ai_method("read", "Optional.")
    def as_optional(self) -> Optional[bytes]:  # noqa: UP045 - the typing form is what is tested
        return None

    @ai_method("read", "Union.")
    def as_union(self) -> bytes | None:
        return None

    @ai_method("read", "List.")
    def as_list(self) -> list[bytearray]:
        return []

    @ai_method("read", "Response.")
    def as_response(self) -> requests.Response:
        return requests.Response()

    @ai_method("read", "String form.")
    def as_string(self) -> "tuple[bytes, str]":
        return b"", ""

    @ai_method("read", "String Optional.")
    def as_string_optional(self) -> "Optional[bytes]":  # noqa: UP045
        return None


class _PlainClient:
    @ai_method("read", "Dict.")
    def as_dict(self) -> dict[str, list[int]]:
        return {}

    @ai_method("read", "String dict.")
    def as_string_dict(self) -> "dict | None":
        return None


@pytest.mark.parametrize(
    "name", ["as_tuple", "as_optional", "as_union", "as_list", "as_response", "as_string", "as_string_optional"]
)
def test_returns_binary_sees_bytes_inside_generics(name):
    assert ai_guard.returns_binary(getattr(_BinaryClient, name))


@pytest.mark.parametrize("name", ["as_dict", "as_string_dict"])
def test_returns_binary_passes_plain_data(name):
    assert not ai_guard.returns_binary(getattr(_PlainClient, name))


def test_check_no_bytes_return_fails_on_a_fake_client(monkeypatch):
    monkeypatch.setattr(ai_guard, "client_cls", lambda family, provider: _BinaryClient)
    with pytest.raises(AssertionError, match="returns"):
        ai_guard.check_no_bytes_return("fake", "fake", {}, {})
    monkeypatch.setattr(ai_guard, "client_cls", lambda family, provider: _PlainClient)
    ai_guard.check_no_bytes_return("fake", "fake", {}, {})


def test_no_network_cannot_be_swallowed_by_except_exception():
    with pytest.raises(AssertionError, match="network access"), ai_guard.no_network():
        try:
            socket.create_connection(("example.com", 80), timeout=1)
        except Exception:  # what a careless adapter __init__ would do
            pass


def test_no_network_cannot_be_swallowed_by_bare_except():
    with pytest.raises(AssertionError, match="network access"), ai_guard.no_network():
        try:
            requests.get("https://example.com", timeout=1)
        except BaseException:  # even this must not hide the attempt
            pass


def test_no_network_restores_sockets_and_passes_quiet_blocks():
    original = socket.create_connection
    with ai_guard.no_network() as attempts:
        pass
    assert attempts == []
    assert socket.create_connection is original
