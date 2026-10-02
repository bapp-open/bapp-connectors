"""Fixture-uri comune pentru testele familiei appstore."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeResponse:
    """Stand-in minimal pentru requests.Response (apeluri cu direct_response=True)."""

    content: bytes = b""
    text: str = ""
    status_code: int = 200
    headers: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status_code < 400
