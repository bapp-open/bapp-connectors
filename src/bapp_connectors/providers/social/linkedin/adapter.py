"""
LinkedIn Page social adapter — implements SocialPort + SocialPublishCapability.

Covers a LinkedIn *organization* (company page) via the versioned REST API
(https://api.linkedin.com/rest/): organization profile, posts with offset
pagination, lifetime share statistics, and publishing text/article posts.

Auth: OAuth2 member access token sent as a Bearer header, plus the Rest.li
protocol headers (X-Restli-Protocol-Version, LinkedIn-Version).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.social import PublishResult, PublishStatus, SocialPrivacy
from bapp_connectors.core.errors import ConnectorError, ValidationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.linkedin.client import LinkedInApiClient
from bapp_connectors.providers.social.linkedin.errors import first_element_or_not_found
from bapp_connectors.providers.social.linkedin.manifest import manifest
from bapp_connectors.providers.social.linkedin.mappers import (
    account_from_org,
    account_stats_from,
    draft_to_post_payload,
    org_urn,
    post_from_linkedin,
    stats_from_share_stats,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.social import (
        SocialAccount,
        SocialAccountStats,
        SocialPost,
        SocialPostDraft,
        SocialPostStats,
    )

_LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


class LinkedInSocialAdapter(SocialPort, SocialPublishCapability, OAuthCapability):
    """
    LinkedIn organization page adapter (versioned REST API).

    Implements SocialPort for a single organization: profile (organization +
    networkSizes follower count), posts with offset pagination (the framework
    cursor is the stringified ``start`` offset), and the universal stats
    interface via organizationalEntityShareStatistics (lifetime aggregates —
    LinkedIn does not scope this endpoint to a period here, so since/until
    are passed through in the result without filtering).

    Implements SocialPublishCapability for text and article-link posts only;
    LinkedIn media posts require the separate initializeUpload flow, which is
    not wrapped yet. Publishing is synchronous — the new post URN comes back
    in the ``x-restli-id`` response header.

    Implements OAuthCapability: LinkedIn OAuth2 authorization code flow.
    Refresh tokens are only issued to approved Marketing Developer Platform
    partners — their absence is tolerated.
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
        self.config = manifest.settings.apply_defaults(config or {})
        self.org_id = str(credentials.get("organization_id", "") or "")
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                provider_name="linkedin",
            )

        self.client = LinkedInApiClient(
            http_client=http_client,
            access_token=credentials.get("access_token", ""),
            version=str(self.config.get("linkedin_version", "202405")),
        )

    @property
    def org_urn(self) -> str:
        return org_urn(self.org_id)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if self.credentials.get("access_token") and self.org_id:
            return True
        # OAuth-flow-only adapter: app credentials alone are enough to run the flow.
        return bool(self._client_id and self._client_secret)

    def test_connection(self) -> ConnectionTestResult:
        try:
            org = self.client.get_organization(self.org_id)
            org_name = org.get("localizedName", self.org_id)
            return ConnectionTestResult(
                success=True,
                message=f"Connected to LinkedIn organization '{org_name}'",
                details=org,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(scopes),
        }
        return f"{_LINKEDIN_AUTH_URL}?{urlencode(params, quote_via=quote)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
            },
        )
        return self._tokens_from_response(response)

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Exchange a refresh token for a new access token.

        LinkedIn only issues refresh tokens to approved Marketing Developer
        Platform partners — when absent from the response, ``refresh_token``
        comes back as ``""``.
        """
        response = self.client.http.call(
            "POST",
            _LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        return self._tokens_from_response(response)

    def _tokens_from_response(self, response: object) -> OAuthTokens:
        """Build OAuthTokens from LinkedIn's accessToken response.

        Refresh tokens may be absent (non-partner apps) — tolerated as ``""``.
        """
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=data.get("refresh_token", ""),
            expires_in=data.get("expires_in"),
            token_type="Bearer",
            extra={
                "credentials": {
                    "access_token": access_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                "refresh_token_expires_in": data.get("refresh_token_expires_in"),
            },
        )

    def list_organizations(self, access_token: str | None = None) -> list[dict]:
        """List the organizations the member administers, for the connect-flow account picker.

        Helper for completing the OAuth flow (not part of OAuthCapability):
        call this with the token returned by ``exchange_code_for_token``
        (defaults to the adapter's stored ``access_token`` credential), let
        the user pick an organization, and store its ``organization_id`` as
        the ``organization_id`` credential.

        Per-organization name lookups are tolerated to fail (missing
        ``r_organization_admin`` visibility, deleted pages) — ``name`` comes
        back as ``""`` in that case.

        Returns a list of ``{"organization_id", "urn", "name"}`` dicts.
        """
        payload = self.client.get_raw(
            "organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED",
            access_token=access_token,
        )
        organizations = []
        for element in payload.get("elements", []):
            urn = element.get("organization", "")
            organization_id = urn.rsplit(":", 1)[-1] if urn else ""
            name = ""
            if organization_id:
                try:
                    org = self.client.get_raw(f"organizations/{organization_id}", access_token=access_token)
                    name = org.get("localizedName", "")
                except ConnectorError:
                    name = ""
            organizations.append({"organization_id": organization_id, "urn": urn, "name": name})
        return organizations

    # ── SocialPort ──

    def get_account(self) -> SocialAccount:
        """Fetch the organization profile + follower count."""
        org = self.client.get_organization(self.org_id)
        followers = self.client.get_follower_count(self.org_id).get("firstDegreeSize")
        return account_from_org(org, followers)

    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        """List the organization's posts, newest first, with offset pagination.

        The framework cursor is LinkedIn's integer ``start`` offset, stringified.
        """
        start = int(cursor) if cursor else 0
        payload = self.client.list_posts(self.org_urn, count=limit, start=start)
        paging = payload.get("paging", {})
        total = paging.get("total")
        has_more = total is not None and paging.get("start", start) + paging.get("count", limit) < total
        return PaginatedResult(
            items=[post_from_linkedin(post) for post in payload.get("elements", [])],
            cursor=str(start + limit) if has_more else None,
            has_more=has_more,
            total=total,
        )

    def get_post(self, post_id: str) -> SocialPost:
        """Fetch a single post by its URN (``urn:li:share:...`` / ``urn:li:ugcPost:...``)."""
        return post_from_linkedin(self.client.get_post(post_id))

    def get_post_stats(self, post_id: str) -> SocialPostStats:
        """Fetch universal stats for a post via organizationalEntityShareStatistics."""
        payload = self.client.get_share_statistics(self.org_urn, [post_id])
        element = first_element_or_not_found(payload, "share statistics", post_id)
        return stats_from_share_stats(element, post_id=post_id)

    def get_account_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SocialAccountStats:
        """Fetch organization-level stats: followers + lifetime share statistics.

        LinkedIn aggregates lifetime totals on this endpoint — ``since``/``until``
        do not filter anything and are passed through in the result.
        """
        payload = self.client.get_share_statistics(self.org_urn)
        elements = payload.get("elements") or [{}]
        followers = self.client.get_follower_count(self.org_id).get("firstDegreeSize")
        stats = account_stats_from(followers, elements[0])
        return stats.model_copy(
            update={
                "account_id": stats.account_id or self.org_id,
                "period_start": since,
                "period_end": until,
            }
        )

    # ── SocialPublishCapability ──

    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Publish a text or article-link post to the organization page.

        Organization posts are always public — non-PUBLIC drafts are rejected.
        Media drafts are rejected too: LinkedIn media posts require the
        separate images/videos initializeUpload flow, which is not wrapped yet.
        Publishing is synchronous — the post URN comes back immediately.
        """
        if draft.privacy != SocialPrivacy.PUBLIC:
            raise ValidationError("LinkedIn organization posts publish publicly only")
        if draft.media_url or draft.file_path or draft.content is not None:
            raise ValidationError(
                "LinkedIn media posts require the initializeUpload flow (images/videos API), "
                "which is not wrapped yet; only text and article-link posts are supported"
            )
        if not (draft.description or draft.title or draft.link):
            raise ValidationError("LinkedIn posts require a message (description/title) or a link")

        post_urn = self.client.create_post(draft_to_post_payload(draft, self.org_urn))
        return PublishResult(
            post_id=post_urn,
            publish_id=post_urn,
            status=PublishStatus.PUBLISHED,
            url=f"https://www.linkedin.com/feed/update/{post_urn}/",
        )

    def check_publish_status(self, publish_id: str) -> PublishResult:
        """LinkedIn publishing is synchronous — an existing post is PUBLISHED."""
        post = self.get_post(publish_id)
        return PublishResult(
            post_id=post.id,
            publish_id=publish_id,
            status=PublishStatus.PUBLISHED,
            url=post.url,
        )
