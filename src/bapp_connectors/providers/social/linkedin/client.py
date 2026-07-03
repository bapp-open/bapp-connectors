"""
LinkedIn REST API client — raw HTTP calls only, no business logic.

All calls go to https://api.linkedin.com/rest/ with the Rest.li protocol
headers (Authorization, X-Restli-Protocol-Version, LinkedIn-Version). URN
path/query parameters are percent-encoded per Rest.li 2.0 (``:`` → ``%3A``).
Post creation returns the new post URN in the ``x-restli-id`` response header
rather than the body, hence ``direct_response=True`` on that call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

from bapp_connectors.core.errors import ProviderError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class LinkedInApiClient:
    """
    Low-level LinkedIn REST API client for an organization page.

    This class only handles HTTP calls and error surfacing. Data
    normalization happens in the adapter via mappers. Non-2xx responses
    raise framework errors from the shared client; error bodies carry
    ``{"message", "serviceErrorCode", "status"}``.
    """

    def __init__(self, http_client: ResilientHttpClient, access_token: str, version: str):
        self.http = http_client
        self.access_token = access_token
        self.version = version

    def _headers(self) -> dict:
        """Rest.li protocol headers sent on every call."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.version,
        }

    def get_raw(self, path: str, access_token: str | None = None) -> dict:
        """GET an arbitrary REST path with the Rest.li headers.

        ``access_token`` overrides the client's stored token for this call
        only (used by connect-flow helpers that run before credentials are
        stored). Non-dict bodies come back as ``{}``.
        """
        headers = self._headers()
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        response = self.http.call("GET", path, headers=headers)
        return response if isinstance(response, dict) else {}

    def get_organization(self, org_id: str) -> dict:
        """GET organizations/{org_id} — fetch the organization profile."""
        return self.http.call("GET", f"organizations/{org_id}", headers=self._headers())

    def get_follower_count(self, org_id: str) -> dict:
        """GET networkSizes/{org_urn} — returns ``{"firstDegreeSize": N}``."""
        org_urn = quote(f"urn:li:organization:{org_id}", safe="")
        return self.http.call(
            "GET",
            f"networkSizes/{org_urn}?edgeType=COMPANY_FOLLOWED_BY_MEMBER",
            headers=self._headers(),
        )

    def list_posts(self, org_urn: str, count: int = 25, start: int = 0) -> dict:
        """GET posts?q=author — returns ``{"elements": [...], "paging": {...}}``."""
        author = quote(org_urn, safe="")
        return self.http.call(
            "GET",
            f"posts?q=author&author={author}&count={count}&start={start}",
            headers=self._headers(),
        )

    def get_post(self, post_urn: str) -> dict:
        """GET posts/{post_urn} — fetch a single post by its URN."""
        return self.http.call("GET", f"posts/{quote(post_urn, safe='')}", headers=self._headers())

    def get_share_statistics(self, org_urn: str, share_urns: list[str] | None = None) -> dict:
        """GET organizationalEntityShareStatistics — lifetime stats for the org or specific shares.

        Returns ``{"elements": [{"totalShareStatistics": {...}, ...}]}`` — one
        element per share when ``share_urns`` is given, a single aggregate
        element otherwise.
        """
        path = (
            "organizationalEntityShareStatistics"
            f"?q=organizationalEntity&organizationalEntity={quote(org_urn, safe='')}"
        )
        for index, share_urn in enumerate(share_urns or []):
            path += f"&shares[{index}]={quote(share_urn, safe='')}"
        return self.http.call("GET", path, headers=self._headers())

    def create_post(self, payload: dict) -> str:
        """POST posts — create a post; returns the new post URN from the x-restli-id header."""
        response = self.http.call(
            "POST",
            "posts",
            direct_response=True,
            headers=self._headers(),
            json=payload,
        )
        if not response.ok:
            raise ProviderError(
                f"LinkedIn post creation failed ({response.status_code}): "
                f"{getattr(response, 'text', '')[:500]}",
                status_code=response.status_code,
            )
        post_urn = response.headers.get("x-restli-id", "")
        if not post_urn:
            raise ProviderError("LinkedIn post creation response is missing the x-restli-id header")
        return post_urn
