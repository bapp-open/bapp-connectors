"""
Facebook Graph API client — raw HTTP calls only, no business logic.

Auth is a Page access token sent as a Bearer header by the shared HTTP client.
Reads are GETs against https://graph.facebook.com/v19.0/{object_id}[/{edge}];
publishing POSTs to an object's edge (feed/photos/videos/video_reels), JSON or
multipart. Reels upload their bytes through the separate rupload host.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Annotated, Any, Literal

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.social.facebook.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

RUPLOAD_VIDEO_URL = "https://rupload.facebook.com/video-upload/v19.0/{video_id}"

# Fixed field lists of the AI-agent reads. The generic ``get_object``/``get_edge``/``get_insights``
# take any object, edge and ``fields`` (``fields=access_token`` on a Page, or ``me/accounts``,
# returns Page tokens), so they are never offered to an agent; the wrappers pin both.
AI_PAGE_FIELDS = "id,name,username,link,about,category,followers_count,fan_count,picture{url},verification_status"
AI_POST_FIELDS = (
    "id,message,created_time,permalink_url,full_picture,attachments{media_type,title,url},"
    "shares,likes.summary(true).limit(0),comments.summary(true).limit(0)"
)
AI_COMMENT_FIELDS = "id,message,created_time,from{id,name},like_count,comment_count,parent{id}"
AI_POST_INSIGHT_METRICS = "post_impressions,post_impressions_unique,post_clicks,post_video_views"
AI_PAGE_INSIGHT_METRICS = "page_impressions,page_impressions_unique,page_post_engagements,page_fans"
AI_VIDEO_STATUS_FIELDS = "status,permalink_url"

InsightsPeriod = Literal["day", "week", "days_28"]


def scrub_graph_paging(value: Any) -> Any:
    """Drop the ``paging.next``/``paging.previous`` URLs anywhere in a Graph payload.

    Graph builds them with the request's ``access_token`` in the query string. The cursors
    stay (``paging.cursors.after`` is what the AI reads take back), plus ``has_next``.
    """
    if isinstance(value, list):
        return [scrub_graph_paging(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key == "paging" and isinstance(item, dict):
            cursors = item.get("cursors") if isinstance(item.get("cursors"), dict) else {}
            out[key] = {
                "cursors": {k: cursors[k] for k in ("before", "after") if k in cursors},
                "has_next": "next" in item,
            }
        else:
            out[key] = scrub_graph_paging(item)
    return out


def day_timestamp(day: date | None, *, end: bool = False) -> int | None:
    """Unix time of the start (or end) of a UTC day, as Graph's ``since``/``until`` take it."""
    if day is None:
        return None
    moment = datetime.combine(day, time.max if end else time.min, tzinfo=UTC)
    return int(moment.timestamp())


class FacebookGraphClient:
    """
    Low-level Facebook Graph API client for a Facebook Page.

    This class only handles HTTP calls and error surfacing. Data normalization
    happens in the adapter via mappers. Non-2xx responses raise framework
    errors from the shared client; 200 bodies carrying ``{"error": {...}}``
    are raised via ``check_payload``.
    """

    def __init__(self, http_client: ResilientHttpClient, page_id: str = ""):
        self.http = http_client
        self.page_id = page_id

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

    def post_edge_multipart(self, object_id: str, edge: str, files: dict, data: dict) -> dict:
        """POST {object_id}/{edge} — create an object with a multipart body (local file/bytes uploads)."""
        response = self.http.call("POST", f"{object_id}/{edge}", files=files, data=data)
        return check_payload(response)

    def upload_hosted_video(self, video_id: str, file_url: str, token: str) -> dict:
        """POST rupload.facebook.com/video-upload/v19.0/{video_id} — Meta pulls the video from ``file_url``.

        rupload is a separate host from the Graph base URL and authenticates with
        an ``Authorization: OAuth <token>`` header (overrides the client's Bearer header).
        """
        response = self.http.call(
            "POST",
            RUPLOAD_VIDEO_URL.format(video_id=video_id),
            headers={"Authorization": f"OAuth {token}", "file_url": file_url},
        )
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

    # ── AI-agent reads: the connected Page, fixed edges and fields ──

    def _page(self) -> str:
        if not self.page_id:
            raise ValidationError("The Facebook connection has no page_id")
        return self.page_id

    @ai_method("read", "The connected Facebook Page: name, username, link, category, followers and fans.")
    def get_page_profile(self) -> dict:
        return self.get_object(self._page(), AI_PAGE_FIELDS)

    @ai_method(
        "read",
        "List the Page's published posts (incl. Reels), newest first, with like/comment/share counts. "
        "Paginate with the 'after' cursor from paging.cursors.",
    )
    def list_page_posts(self, limit: int | None = None, after: Annotated[str, "free_text"] | None = None) -> dict:
        return scrub_graph_paging(self.get_edge(self._page(), "posts", fields=AI_POST_FIELDS, limit=limit, after=after))

    @ai_method("read", "Get one Page post by its ID ({page_id}_{post_id}).")
    def get_post_details(self, post_id: str) -> dict:
        return scrub_graph_paging(self.get_object(post_id, AI_POST_FIELDS))

    @ai_method(
        "read",
        "List the comments of a Page post (or the replies of a comment), oldest first. "
        "Paginate with the 'after' cursor from paging.cursors.",
    )
    def list_post_comments(
        self, post_id: str, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        return scrub_graph_paging(
            self.get_edge(post_id, "comments", fields=AI_COMMENT_FIELDS, limit=limit, after=after)
        )

    @ai_method("read", "Lifetime insights of a Page post: impressions, unique impressions, clicks, video views.")
    def get_post_insights(self, post_id: str) -> dict:
        return scrub_graph_paging(self.get_insights(post_id, AI_POST_INSIGHT_METRICS))

    @ai_method(
        "read",
        "Page insights (impressions, unique impressions, post engagements, fans) per day/week/28 days "
        "between since and until (YYYY-MM-DD).",
    )
    def get_page_insights(
        self, since: date | None = None, until: date | None = None, period: InsightsPeriod = "day"
    ) -> dict:
        payload = self.get_insights(
            self._page(),
            AI_PAGE_INSIGHT_METRICS,
            period=period,
            since=day_timestamp(since),
            until=day_timestamp(until, end=True),
        )
        return scrub_graph_paging(payload)

    @ai_method("read", "Processing/publishing status of a video or Reel uploaded to the Page, by its video ID.")
    def get_video_publish_status(self, video_id: str) -> dict:
        return self.get_object(video_id, AI_VIDEO_STATUS_FIELDS)
