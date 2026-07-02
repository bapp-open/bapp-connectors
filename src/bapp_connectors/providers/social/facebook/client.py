"""
Facebook Graph API client — raw HTTP calls only, no business logic.

Auth is a Page access token sent as a Bearer header by the shared HTTP client.
All calls are GETs against https://graph.facebook.com/v19.0/{object_id}[/{edge}].
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bapp_connectors.providers.social.facebook.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class FacebookGraphClient:
    """
    Low-level Facebook Graph API client for a Facebook Page.

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

    def get_insights(
        self,
        object_id: str,
        metric: str,
        period: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> dict:
        """GET {object_id}/insights — fetch insights metrics for a page or post."""
        query = {"metric": metric, "period": period, "since": since, "until": until}
        query = {k: v for k, v in query.items() if v is not None}
        response = self.http.call("GET", f"{object_id}/insights", params=query)
        return check_payload(response)
