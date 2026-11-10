"""
Instagram Graph API client — raw HTTP calls only, no business logic.

Auth is a Page/user access token sent as a Bearer header by the shared HTTP
client. Reads are GETs against https://graph.facebook.com/v19.0/{object_id}
[/{edge}]; publishing POSTs to the IG user's media / media_publish edges.
"""

from __future__ import annotations

import logging
import re
from datetime import date  # noqa: TC003 -- runtime: get_type_hints on the AI reads
from typing import TYPE_CHECKING, Annotated, Literal

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.social.facebook.client import day_timestamp, scrub_graph_paging
from bapp_connectors.providers.social.instagram.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

# Fixed field lists of the AI-agent reads (the generic get_object/get_edge/get_insights and
# business_discovery take any object and any ``fields``; they are never offered to an agent).
AI_ACCOUNT_FIELDS = "id,username,name,biography,profile_picture_url,followers_count,follows_count,media_count,website"
AI_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp,like_count,comments_count"
)
AI_COMMENT_FIELDS = "id,text,timestamp,username,like_count"
AI_DISCOVERY_FIELDS = "id,username,name,biography,website,profile_picture_url,followers_count,media_count"
AI_CONTAINER_FIELDS = "status_code,status"
AI_MEDIA_INSIGHT_METRICS = {"post": "impressions,reach,saved", "video": "plays,video_views"}
AI_ACCOUNT_INSIGHT_METRICS = "impressions,reach"

#: An Instagram handle; it goes into a Graph field expression, so nothing else is sent.
USERNAME_RE = re.compile(r"[A-Za-z0-9._]{1,30}")


class InstagramGraphClient:
    """
    Low-level Instagram Graph API client for a Business/Creator account.

    This class only handles HTTP calls and error surfacing. Data normalization
    happens in the adapter via mappers. Non-2xx responses raise framework
    errors from the shared client; 200 bodies carrying ``{"error": {...}}``
    are raised via ``check_payload``.
    """

    def __init__(self, http_client: ResilientHttpClient, ig_user_id: str = ""):
        self.http = http_client
        self.ig_user_id = ig_user_id

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

    # ── AI-agent reads: the connected account, fixed edges and fields ──

    def _user(self) -> str:
        if not self.ig_user_id:
            raise ValidationError("The Instagram connection has no ig_user_id")
        return self.ig_user_id

    @ai_method("read", "The connected Instagram account: username, name, bio, followers, follows, media count.")
    def get_profile(self) -> dict:
        return self.get_object(self._user(), AI_ACCOUNT_FIELDS)

    @ai_method(
        "read",
        "List the account's media (posts, reels, carousels), newest first, with like and comment counts. "
        "Paginate with the 'after' cursor from paging.cursors.",
    )
    def list_media(self, limit: int | None = None, after: Annotated[str, "free_text"] | None = None) -> dict:
        return scrub_graph_paging(
            self.get_edge(self._user(), "media", fields=AI_MEDIA_FIELDS, limit=limit, after=after)
        )

    @ai_method("read", "Get one media object of the account by its ID.")
    def get_media(self, media_id: str) -> dict:
        return self.get_object(media_id, AI_MEDIA_FIELDS)

    @ai_method(
        "read",
        "List the comments of a media object. Paginate with the 'after' cursor from paging.cursors.",
    )
    def list_media_comments(
        self, media_id: str, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        return scrub_graph_paging(
            self.get_edge(media_id, "comments", fields=AI_COMMENT_FIELDS, limit=limit, after=after)
        )

    @ai_method(
        "read",
        "Lifetime insights of a media object: kind 'post' = impressions, reach, saved; "
        "kind 'video' = plays, video views.",
    )
    def get_media_insights(self, media_id: str, kind: Literal["post", "video"] = "post") -> dict:
        return scrub_graph_paging(self.get_insights(media_id, AI_MEDIA_INSIGHT_METRICS[kind]))

    @ai_method("read", "Daily account insights (impressions, reach) between since and until (YYYY-MM-DD).")
    def get_account_insights(self, since: date | None = None, until: date | None = None) -> dict:
        payload = self.get_insights(
            self._user(),
            AI_ACCOUNT_INSIGHT_METRICS,
            period="day",
            since=day_timestamp(since),
            until=day_timestamp(until, end=True),
        )
        return scrub_graph_paging(payload)

    @ai_method("read", "Status of a media container being published (IN_PROGRESS, FINISHED, ERROR, ...), by its ID.")
    def get_container_status(self, container_id: str) -> dict:
        return self.get_object(container_id, AI_CONTAINER_FIELDS)

    @ai_method("read", "Public profile of another Instagram Business/Creator account by its exact username.")
    def lookup_business_account(self, username: str) -> dict:
        handle = username.strip().removeprefix("@")
        if not USERNAME_RE.fullmatch(handle):
            raise ValidationError("Not an Instagram username")
        return self.business_discovery(self._user(), handle, AI_DISCOVERY_FIELDS)

    @ai_method("read", "Product catalogs the account can tag products from.")
    def list_catalogs(self) -> dict:
        return scrub_graph_paging(self.available_catalogs(self._user()))

    @ai_method("read", "Search taggable products of one of the account's catalogs by name or retailer ID.")
    def search_catalog_products(self, catalog_id: str, query: Annotated[str, "free_text"]) -> dict:
        return scrub_graph_paging(self.catalog_product_search(self._user(), catalog_id, query))
