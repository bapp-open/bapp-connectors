"""
Pinterest social adapter — implements SocialPort.

Exposes the connected Pinterest account profile, its pins with bookmark
pagination, and universal statistics via the Pinterest API v5 analytics
endpoints. Publishes image pins by URL.

Auth: Pinterest OAuth user access token sent as a Bearer header.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.social import PublishResult, PublishStatus, SocialMediaType
from bapp_connectors.core.errors import AuthenticationError, ValidationError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.pinterest.client import PinterestApiClient
from bapp_connectors.providers.social.pinterest.errors import error_message, not_found
from bapp_connectors.providers.social.pinterest.manifest import manifest
from bapp_connectors.providers.social.pinterest.mappers import (
    account_from_pinterest,
    account_stats_from_analytics,
    post_from_pin,
    stats_from_pin_analytics,
)

if TYPE_CHECKING:
    from bapp_connectors.core.dto.social import (
        SocialAccount,
        SocialAccountStats,
        SocialPost,
        SocialPostDraft,
        SocialPostStats,
    )

_PINTEREST_AUTH_URL = "https://www.pinterest.com/oauth/"
_PINTEREST_TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"

PIN_METRIC_TYPES = ("IMPRESSION", "PIN_CLICK", "OUTBOUND_CLICK", "SAVE")

_PIN_STATS_WINDOW_DAYS = 90  # Pinterest caps pin analytics ranges at 90 days
_ACCOUNT_STATS_DEFAULT_DAYS = 30


def _pin_url(pin_id: str) -> str:
    return f"https://www.pinterest.com/pin/{pin_id}/"


class PinterestSocialAdapter(SocialPort, SocialPublishCapability, OAuthCapability):
    """
    Pinterest API v5 adapter.

    Implements SocialPort: account profile, pin listing with bookmark
    pagination, single-pin lookup, and the universal stats interface via the
    pin/account analytics endpoints (pin stats cover the last 90 days).
    Implements SocialPublishCapability for image pins created from a public
    URL — pin creation is synchronous. Implements OAuthCapability via the
    Pinterest authorization code flow (token calls use HTTP Basic auth with
    the app credentials).
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
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(token=credentials.get("token", "")),
                provider_name="pinterest",
            )

        self.client = PinterestApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        if missing:
            return False
        # Either a ready-to-use access token, or the app credentials needed
        # to obtain one via the OAuth flow.
        has_token = bool(self.credentials.get("token"))
        has_oauth_app = bool(self._client_id and self._client_secret)
        return has_token or has_oauth_app

    def test_connection(self) -> ConnectionTestResult:
        try:
            user = self.client.get_user_account()
            username = user.get("username") or "unknown"
            return ConnectionTestResult(
                success=True,
                message=f"Connected as {username}",
                details=user,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(scopes),
            "state": state,
        }
        return f"{_PINTEREST_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _PINTEREST_TOKEN_URL,
            headers={"Authorization": self._basic_auth_header()},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        return self._tokens_from_response(response)

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _PINTEREST_TOKEN_URL,
            headers={"Authorization": self._basic_auth_header()},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        # Pinterest keeps the same refresh token until it expires — fall back
        # to the incoming one when the response omits it.
        return self._tokens_from_response(response, fallback_refresh_token=refresh_token)

    def _basic_auth_header(self) -> str:
        """Pinterest token calls authenticate with Basic base64(client_id:client_secret)."""
        raw = f"{self._client_id}:{self._client_secret}".encode()
        return f"Basic {b64encode(raw).decode()}"

    def _tokens_from_response(self, response: object, fallback_refresh_token: str = "") -> OAuthTokens:
        """Build OAuthTokens from Pinterest's oauth/token response."""
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        if not access_token:
            raise AuthenticationError(f"Pinterest OAuth error: {error_message(response)}")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=data.get("refresh_token") or fallback_refresh_token,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                "scope": data.get("scope", ""),
                "refresh_token_expires_in": data.get("refresh_token_expires_in"),
            },
        )

    # ── SocialPort ──

    def get_account(self) -> SocialAccount:
        """Fetch the connected Pinterest account profile."""
        return account_from_pinterest(self.client.get_user_account())

    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        """List the account's pins with bookmark pagination.

        The cursor is Pinterest's opaque ``bookmark`` string.
        """
        data = self.client.list_pins(page_size=limit, bookmark=cursor)
        items = [post_from_pin(pin) for pin in data.get("items", [])]
        bookmark = data.get("bookmark") or None
        return PaginatedResult(items=items, cursor=bookmark, has_more=bool(bookmark))

    def get_post(self, post_id: str) -> SocialPost:
        """Fetch a single pin by ID."""
        pin = self.client.get_pin(post_id)
        if not pin.get("id"):
            raise not_found(f"pin {post_id}")
        return post_from_pin(pin)

    def get_post_stats(self, post_id: str) -> SocialPostStats:
        """Fetch universal statistics for a pin over the last 90 days."""
        end = datetime.now(UTC).date()
        start = end - timedelta(days=_PIN_STATS_WINDOW_DAYS)
        payload = self.client.get_pin_analytics(
            post_id,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            metric_types=PIN_METRIC_TYPES,
        )
        return stats_from_pin_analytics(post_id, payload)

    def get_account_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SocialAccountStats:
        """Fetch universal account statistics over the given period (default last 30 days).

        Followers and pin counts are lifetime counters from the user profile;
        impressions come from user_account/analytics scoped to the period.
        """
        end = (until or datetime.now(UTC)).date()
        start = (since or datetime.now(UTC) - timedelta(days=_ACCOUNT_STATS_DEFAULT_DAYS)).date()
        user = self.client.get_user_account()
        payload = self.client.get_user_analytics(start_date=start.isoformat(), end_date=end.isoformat())
        stats = account_stats_from_analytics(payload, user)
        return stats.model_copy(update={"period_start": since, "period_end": until})

    # ── SocialPublishCapability ──

    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Publish an image pin from a public URL. Pin creation is synchronous.

        Every pin needs a board: ``draft.extra['board_id']`` or the
        ``default_board_id`` setting.
        """
        if draft.media_type == SocialMediaType.TEXT:
            raise ValidationError("Pinterest has no text posts — pins require an image or video.")
        if draft.media_type in (SocialMediaType.VIDEO, SocialMediaType.SHORT_VIDEO):
            raise ValidationError(
                "Pinterest video pins need the asynchronous media upload API, "
                "which is not wrapped yet."
            )
        if draft.media_type != SocialMediaType.IMAGE:
            raise ValidationError(f"Pinterest cannot publish media of type '{draft.media_type}'.")

        board_id = draft.extra.get("board_id") or self.config.get("default_board_id")
        if not board_id:
            raise ValidationError(
                "Pinterest pins require a board — set draft.extra['board_id'] "
                "or the default_board_id setting."
            )
        if not draft.media_url:
            raise ValidationError(
                "Pinterest image pins require a publicly accessible media_url; "
                "uploading from file_path/content uses the media upload flow, "
                "which is not wrapped yet."
            )

        payload = {
            "board_id": board_id,
            "title": draft.title,
            "description": draft.description,
            "media_source": {"source_type": "image_url", "url": draft.media_url},
        }
        if draft.link:
            payload["link"] = draft.link
        response = self.client.create_pin(payload)
        pin_id = str(response.get("id", ""))
        return PublishResult(
            post_id=pin_id,
            status=PublishStatus.PUBLISHED,
            url=_pin_url(pin_id),
            extra=response,
        )

    def check_publish_status(self, publish_id: str) -> PublishResult:
        """Pin creation is synchronous — an existing pin is PUBLISHED."""
        pin = self.client.get_pin(publish_id)
        pin_id = str(pin.get("id") or publish_id)
        return PublishResult(
            post_id=pin_id,
            publish_id=publish_id,
            status=PublishStatus.PUBLISHED,
            url=_pin_url(pin_id),
        )
