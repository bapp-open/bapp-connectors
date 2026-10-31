"""
Meta adapter — implements OAuthCapability + SocialDestinationsCapability.

One Meta login (a long-lived *user* token, sent as a Bearer header) reaches
every Facebook Page the user manages and the Instagram Business accounts
linked to them. ``list_destinations`` hands out each target with its Page
access token, ready to drive the ``facebook`` / ``instagram`` adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability, SocialDestinationsCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import BasePort
from bapp_connectors.providers.social.facebook.http import GraphHttpClient
from bapp_connectors.providers.social.meta.client import MetaGraphClient
from bapp_connectors.providers.social.meta.errors import check_payload
from bapp_connectors.providers.social.meta.manifest import manifest
from bapp_connectors.providers.social.meta.mappers import destinations_from_page

if TYPE_CHECKING:
    from bapp_connectors.core.dto.social import SocialDestination

_OAUTH_DIALOG_URL = "https://www.facebook.com/v19.0/dialog/oauth"

ACCOUNT_FIELDS = (
    "id,name,username,picture{url},access_token,instagram_business_account{id,username,name,profile_picture_url}"
)


class MetaAdapter(BasePort, OAuthCapability, SocialDestinationsCapability):
    """
    Meta (Facebook + Instagram) connection adapter (Graph API v19.0).

    OAuth: the authorization code is exchanged for a short-lived user token,
    which is immediately traded (``fb_exchange_token``) for a long-lived one.
    ``expires_in`` is reported as ``None``: Page tokens derived from a
    long-lived user token do not expire, so reconnection is driven by
    authentication errors rather than a refresh schedule.
    """

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = config or {}
        self._app_id = credentials.get("app_id", "")
        self._app_secret = credentials.get("app_secret", "")

        if http_client is None:
            http_client = GraphHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="meta",
            )

        self.client = MetaGraphClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if self._app_id and self._app_secret:
            # App credentials alone are enough to run the OAuth flow.
            return True
        return bool(self.credentials.get("token"))

    def test_connection(self) -> ConnectionTestResult:
        try:
            me = self.client.get_object("me", "id,name")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to Meta as '{me.get('name', me.get('id', ''))}'",
                details=me,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        params = {
            "client_id": self._app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(self.manifest.auth.oauth.scopes),
        }
        return f"{_OAUTH_DIALOG_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        """Exchange the code for a short-lived user token, then trade it for a long-lived one."""
        data = self._token_request(
            {
                "client_id": self._app_id,
                "redirect_uri": redirect_uri,
                "client_secret": self._app_secret,
                "code": code,
            }
        )
        return self.refresh_token(data.get("access_token", ""))

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Trade a valid (short- or long-lived) user token for a fresh long-lived one.

        Meta has no refresh tokens; ``refresh_token`` is the current access token.
        """
        data = self._token_request(
            {
                "grant_type": "fb_exchange_token",
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "fb_exchange_token": refresh_token,
            }
        )
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token="",  # Meta issues no refresh tokens
            expires_in=None,  # derived Page tokens do not expire; reconnect on auth errors
            token_type=data.get("token_type", "Bearer"),
            extra={"credentials": {"token": access_token}},
        )

    def _token_request(self, params: dict) -> dict:
        response = self.client.http.call("GET", "oauth/access_token", params=params)
        return check_payload(response if isinstance(response, dict) else {})

    # ── SocialDestinationsCapability ──

    def list_destinations(self) -> list[SocialDestination]:
        """Every managed Facebook Page, each followed by its linked Instagram account (if any)."""
        destinations: list[SocialDestination] = []
        after: str | None = None
        while True:
            payload = self.client.get_edge("me", "accounts", fields=ACCOUNT_FIELDS, after=after)
            for page in payload.get("data", []):
                destinations.extend(destinations_from_page(page))
            paging = payload.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not paging.get("next") or not after:
                return destinations
