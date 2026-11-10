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
from datetime import date  # noqa: TC003 -- runtime: get_type_hints on the AI reads
from typing import TYPE_CHECKING, Annotated

from bapp_connectors.core.ai import ai_method
from bapp_connectors.providers.social.facebook.client import day_timestamp, scrub_graph_paging
from bapp_connectors.providers.social.threads.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

# Fixed field lists of the AI-agent reads (the generic get_object/get_edge/get_insights take any
# object, edge and ``fields``; they are never offered to an agent). "me" is the token owner.
AI_USER_FIELDS = "id,username,name,threads_profile_picture_url,threads_biography"
AI_MEDIA_FIELDS = "id,text,media_type,media_url,permalink,timestamp,username,is_quote_post"
AI_REPLY_FIELDS = "id,text,username,timestamp,permalink,media_type,has_replies,hide_status"
AI_CONTAINER_FIELDS = "status,error_message"
AI_MEDIA_INSIGHT_METRICS = "views,likes,replies,reposts,quotes,shares"
AI_USER_INSIGHT_METRICS = "views,likes,replies,reposts,quotes,followers_count"


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

    # ── AI-agent reads: the token owner, fixed edges and fields ──

    @ai_method("read", "The connected Threads profile: username, name, picture, biography.")
    def get_profile(self) -> dict:
        return self.get_object("me", AI_USER_FIELDS)

    @ai_method(
        "read",
        "List the profile's threads, newest first. Paginate with the 'after' cursor from paging.cursors.",
    )
    def list_threads(self, limit: int | None = None, after: Annotated[str, "free_text"] | None = None) -> dict:
        return scrub_graph_paging(self.get_edge("me", "threads", fields=AI_MEDIA_FIELDS, limit=limit, after=after))

    @ai_method("read", "Get one thread by its media ID.")
    def get_thread(self, media_id: str) -> dict:
        return self.get_object(media_id, AI_MEDIA_FIELDS)

    @ai_method(
        "read",
        "List the direct replies to a thread. Paginate with the 'after' cursor from paging.cursors.",
    )
    def list_replies(
        self, media_id: str, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        return scrub_graph_paging(self.get_edge(media_id, "replies", fields=AI_REPLY_FIELDS, limit=limit, after=after))

    @ai_method("read", "Insights of one thread: views, likes, replies, reposts, quotes, shares.")
    def get_thread_insights(self, media_id: str) -> dict:
        return scrub_graph_paging(self.get_insights(media_id, AI_MEDIA_INSIGHT_METRICS))

    @ai_method(
        "read",
        "Profile insights (views, likes, replies, reposts, quotes, followers) between since and until (YYYY-MM-DD).",
    )
    def get_profile_insights(self, since: date | None = None, until: date | None = None) -> dict:
        payload = self.get_insights(
            "me",
            AI_USER_INSIGHT_METRICS,
            edge="threads_insights",
            since=day_timestamp(since),
            until=day_timestamp(until, end=True),
        )
        return scrub_graph_paging(payload)

    @ai_method("read", "Status of a media container being published (IN_PROGRESS, FINISHED, ERROR, ...), by its ID.")
    def get_container_status(self, container_id: str) -> dict:
        return self.get_object(container_id, AI_CONTAINER_FIELDS)
