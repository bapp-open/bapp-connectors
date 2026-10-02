"""Fixture-uri comune pentru testele familiei appstore."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest


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


def _read(path_var: str) -> str:
    path = os.environ.get(path_var, "")
    return Path(path).read_text() if path and Path(path).exists() else ""


APPLE_ENV = {
    "issuer_id": os.environ.get("BAPP_APPLE_ISSUER_ID", ""),
    "key_id": os.environ.get("BAPP_APPLE_KEY_ID", ""),
    "private_key": _read("BAPP_APPLE_PRIVATE_KEY_PATH"),
    "vendor_number": os.environ.get("BAPP_APPLE_VENDOR_NUMBER", ""),
}
APPLE_APP_ID = os.environ.get("BAPP_APPLE_APP_ID", "")
GOOGLE_ENV = {
    "service_account_json": _read("BAPP_GOOGLE_PLAY_SA_PATH"),
    "bucket_uri": os.environ.get("BAPP_GOOGLE_PLAY_BUCKET", ""),
    "package_names": os.environ.get("BAPP_GOOGLE_PLAY_PACKAGE", ""),
}
STEAM_ENV = {
    "financial_api_key": os.environ.get("BAPP_STEAM_FINANCIAL_API_KEY", ""),
    "app_ids": os.environ.get("BAPP_STEAM_APP_IDS", ""),
}

skip_unless_apple = pytest.mark.skipif(not all(APPLE_ENV.values()), reason="BAPP_APPLE_* lipsesc")
skip_unless_google = pytest.mark.skipif(
    not (GOOGLE_ENV["service_account_json"] and GOOGLE_ENV["bucket_uri"]), reason="BAPP_GOOGLE_PLAY_* lipsesc"
)
skip_unless_steam = pytest.mark.skipif(not all(STEAM_ENV.values()), reason="BAPP_STEAM_* lipsesc")
