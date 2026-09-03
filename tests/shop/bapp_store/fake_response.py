"""Minimal requests.Response stand-in for calls made with direct_response=True."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Any = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self.payload
