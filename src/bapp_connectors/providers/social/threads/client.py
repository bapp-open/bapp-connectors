"""
Threads API client — raw HTTP calls only, no business logic.

Auth is a Threads user access token sent as a Bearer header by the shared
HTTP client. Reads are GETs against https://graph.threads.net/v1.0/{id}[/{edge}]
("me" resolves to the token owner); publishing POSTs to me/threads and
me/threads_publish with the parameters in the query string, which the
Threads API accepts for publishing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bapp_connectors.providers.social.threads.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class ThreadsApiClient:
    """
    Low-level Threads API client for the connected user.

    This class only handles HTTP calls and error surfacing. Data normalization
    happens in the adapter via mappers. Non-2xx responses raise framework
    errors from the shared client; 200 bodies carrying ``{"error": {...}}``
    are raised via ``check_payload``.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def get_object(self, object_id: str, fields: str, **params) -> dict:
        """GET {object_id} — fetch a single Threads object ("me" = token owner)."""
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
        """POST {object_id}/{edge} — the Threads API accepts publishing parameters as query params."""
        query = {k: v for k, v in payload.items() if v is not None}
        response = self.http.call("POST", f"{object_id}/{edge}", params=query)
        return check_payload(response)

    def get_insights(self, object_id: str, metric: str, edge: str = "insights", **params) -> dict:
        """GET {object_id}/{edge} — fetch insights metrics for a media object or the user.

        Media insights live on ``{media_id}/insights``; user insights live on
        ``me/threads_insights`` (pass ``edge="threads_insights"``).
        """
        query = {"metric": metric, **{k: v for k, v in params.items() if v is not None}}
        response = self.http.call("GET", f"{object_id}/{edge}", params=query)
        return check_payload(response)
