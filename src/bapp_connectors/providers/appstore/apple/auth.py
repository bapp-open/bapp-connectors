"""JWT ES256 pentru Apple: App Store Connect API (fara `bid`) si App Store Server API (cu `bid`)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from bapp_connectors.core.http.auth import BaseAuthStrategy

if TYPE_CHECKING:
    from collections.abc import Callable

APPLE_AUDIENCE = "appstoreconnect-v1"


def normalize_pem(text: str) -> str:
    """Cheile lipite din UI vin uneori cu `\\n` literal in loc de newline."""
    return text.replace("\\n", "\n").strip()


class AppleJwtAuth(BaseAuthStrategy):
    """Genereaza si cache-uieste tokenul JWT; il regenereaza cu 60 s inainte de expirare."""

    def __init__(
        self,
        issuer_id: str,
        key_id: str,
        private_key: str,
        *,
        bundle_id: str | None = None,
        ttl_seconds: int = 1200,
        clock: Callable[[], float] = time.time,
    ):
        self.issuer_id = issuer_id
        self.key_id = key_id
        self.private_key = normalize_pem(private_key)
        self.bundle_id = bundle_id
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._token: str | None = None
        self._expires_at: float = 0.0

    def token(self) -> str:
        import jwt  # extra `appstore`

        now = self._clock()
        if self._token and now < self._expires_at - 60:
            return self._token
        claims: dict = {
            "iss": self.issuer_id,
            "iat": int(now),
            "exp": int(now) + self.ttl_seconds,
            "aud": APPLE_AUDIENCE,
        }
        if self.bundle_id:
            claims["bid"] = self.bundle_id
        self._token = jwt.encode(claims, self.private_key, algorithm="ES256", headers={"kid": self.key_id, "typ": "JWT"})
        self._expires_at = now + self.ttl_seconds
        return self._token

    def apply_to_headers(self, headers: dict) -> dict:
        headers["Authorization"] = f"Bearer {self.token()}"
        return headers
