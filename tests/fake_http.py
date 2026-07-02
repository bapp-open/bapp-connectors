"""
Fake ResilientHttpClient for unit-testing API-backed adapters without network.

Register canned responses matched by HTTP method + path substring. Every call
is recorded in ``calls`` for assertions on outgoing payloads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecordedCall:
    """One HTTP call made through the fake client."""

    method: str
    path: str
    kwargs: dict


@dataclass
class FakeHttpClient:
    """
    Drop-in stub for ResilientHttpClient.

    ``responses`` is a list of (method, path_substring, response) rules,
    checked in order. ``method`` may be None to match any method. ``response``
    may be a value (returned as-is) or a callable ``(method, path, kwargs) -> value``.
    """

    responses: list[tuple[str | None, str, Any]] = field(default_factory=list)
    base_url: str = "https://fake.local/"
    calls: list[RecordedCall] = field(default_factory=list)

    def add(self, method: str | None, path_substring: str, response: Any | Callable) -> None:
        self.responses.append((method, path_substring, response))

    def call(self, method: str, path: str, direct_response: bool = False, headers: dict | None = None, **kwargs):
        self.calls.append(RecordedCall(method=method, path=path, kwargs={"headers": headers, **kwargs}))
        for rule_method, substring, response in self.responses:
            if (rule_method is None or rule_method == method) and substring in path:
                if callable(response):
                    return response(method, path, kwargs)
                return response
        raise AssertionError(f"FakeHttpClient: no canned response for {method} {path}")

    def get(self, path: str, **kwargs):
        return self.call("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.call("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.call("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.call("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.call("DELETE", path, **kwargs)

    def last_call(self) -> RecordedCall:
        assert self.calls, "FakeHttpClient: no calls recorded"
        return self.calls[-1]
