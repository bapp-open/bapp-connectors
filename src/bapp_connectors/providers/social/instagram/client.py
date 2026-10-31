"""
Instagram Graph API client — raw HTTP calls only, no business logic.

Auth is a Page/user access token sent as a Bearer header by the shared HTTP
client. Reads are GETs against https://graph.facebook.com/v19.0/{object_id}
[/{edge}]; publishing POSTs to the IG user's media / media_publish edges.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bapp_connectors.providers.social.instagram.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class InstagramGraphClient:
    """
    Low-level Instagram Graph API client for a Business/Creator account.

    This class only handles HTTP calls and error surfacing. Data normalization
    happens in the adapter via mappers. Non-2xx responses raise framework
    errors from the shared client; 200 bodies carrying ``{"error": {...}}``
    are raised via ``check_payload``.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def get_object(self, object_id: str, fields: str, **params) -> dict:
        """GET {object_id} — fetch a single Graph object with the given fields."""
        query = {"fields": fields, **{k: v for k, v in params.items() if v is not None}}
        response = self.http.call("GET", object_id, params=query)
        return check_payload(response)

    def get_edge(
        self,
        object_id: str,
        edge: str,
        fields: str | None = None,
        limit: int | None = None,
        after: str | None = None,
        **params,
    ) -> dict:
        """GET {object_id}/{edge} — fetch a paginated connection of an object."""
        query = {"fields": fields, "limit": limit, "after": after, **params}
        query = {k: v for k, v in query.items() if v is not None}
        response = self.http.call("GET", f"{object_id}/{edge}", params=query)
        return check_payload(response)

    def post_edge(self, object_id: str, edge: str, payload: dict) -> dict:
        """POST {object_id}/{edge} — create an object on a connection (JSON payload)."""
        response = self.http.call("POST", f"{object_id}/{edge}", json=payload)
        return check_payload(response)

    def get_insights(
        self,
        object_id: str,
        metric: str,
        period: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> dict:
        """GET {object_id}/insights — fetch insights metrics for the account or a media object."""
        query = {"metric": metric, "period": period, "since": since, "until": until}
        query = {k: v for k, v in query.items() if v is not None}
        response = self.http.call("GET", f"{object_id}/insights", params=query)
        return check_payload(response)

    def business_discovery(self, ig_user_id: str, username: str, fields: str) -> dict:
        """GET {ig_user_id}?fields=business_discovery.username(<username>){fields} — public Business/Creator profile."""
        return self.get_object(ig_user_id, f"business_discovery.username({username}){{{fields}}}")

    def available_catalogs(self, ig_user_id: str) -> dict:
        """GET {ig_user_id}/available_catalogs — product catalogs usable for shopping tags."""
        return self.get_edge(ig_user_id, "available_catalogs")

    def catalog_product_search(self, ig_user_id: str, catalog_id: str, query: str) -> dict:
        """GET {ig_user_id}/catalog_product_search — taggable products of a catalog matching ``query``."""
        return self.get_edge(ig_user_id, "catalog_product_search", catalog_id=catalog_id, q=query)
