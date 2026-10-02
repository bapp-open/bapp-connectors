"""Autentificare Google cu service account: JWT RS256 -> access token OAuth2."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.http.auth import BaseAuthStrategy

if TYPE_CHECKING:
    from collections.abc import Callable

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE_STORAGE_RO = "https://www.googleapis.com/auth/devstorage.read_only"
SCOPE_ANDROID_PUBLISHER = "https://www.googleapis.com/auth/androidpublisher"


def parse_service_account(value: str | dict) -> dict:
    try:
        data = json.loads(value) if isinstance(value, str) else dict(value)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(f"JSON-ul service account-ului nu se poate citi: {exc}") from exc
    missing = [k for k in ("client_email", "private_key") if not data.get(k)]
    if missing:
        raise ConfigurationError(f"Service account fara campurile: {', '.join(missing)}")
    data["private_key"] = data["private_key"].replace("\\n", "\n").strip()
    data.setdefault("token_uri", TOKEN_URI)
    return data


def bucket_name_from_uri(uri: str) -> str:
    return uri.strip().removeprefix("gs://").strip("/").split("/")[0]


def _default_token_fetcher(token_uri: str, assertion: str) -> dict:
    import requests

    response = requests.post(
        token_uri,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


class GoogleServiceAccountAuth(BaseAuthStrategy):
    def __init__(
        self,
        service_account: dict,
        scopes: list[str],
        *,
        token_fetcher: Callable[[str, str], dict] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.service_account = service_account
        self.scopes = scopes
        self._fetch = token_fetcher or _default_token_fetcher
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    def _assertion(self, now: float) -> str:
        import jwt

        claims = {
            "iss": self.service_account["client_email"],
            "scope": " ".join(self.scopes),
            "aud": self.service_account["token_uri"],
            "iat": int(now),
            "exp": int(now) + 3600,
        }
        return jwt.encode(claims, self.service_account["private_key"], algorithm="RS256")

    def access_token(self) -> str:
        now = self._clock()
        if self._token and now < self._expires_at - 60:
            return self._token
        payload = self._fetch(self.service_account["token_uri"], self._assertion(now))
        self._token = payload["access_token"]
        self._expires_at = now + float(payload.get("expires_in", 3600))
        return self._token

    def apply_to_headers(self, headers: dict) -> dict:
        headers["Authorization"] = f"Bearer {self.access_token()}"
        return headers
