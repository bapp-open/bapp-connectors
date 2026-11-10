"""Guard on the ``@ai_method`` markers of the social provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
social account token. Every one of them was read down to its HTTP request; the lists below are
that review. Publishing is ``write`` (or unmarked when the method is a generic edge POST).

The Graph API clients (facebook, instagram, threads) expose generic ``get_object``/``get_edge``
methods that take any object, edge and ``fields``: ``fields=access_token`` on a Page, or
``me/accounts``, returns Page tokens. Those are never ``read``; the agent gets wrappers with a
fixed edge and fixed fields, pinned to the connected Page / IG account / token owner, and the
``paging.next`` URLs (Graph puts the access token in them) are dropped from what they return.
The ``meta`` connection holds a *user* token whose only job is listing Pages with their Page
tokens: its adapter hands out no AI client at all.
"""

from __future__ import annotations

import inspect
from datetime import date
from unittest.mock import MagicMock

import pytest

from bapp_connectors.core.ai import ai_methods
from bapp_connectors.core.errors import ValidationError
from tests.core import ai_guard

FAMILY = "social"
SOCIAL_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "facebook": {
        "get_page_insights",  # GET {page}/insights, fixed metrics; period is a Literal, since/until dates
        "get_page_profile",  # GET {page}, fixed fields (no access_token)
        "get_post_details",  # GET {post_id}, fixed fields
        "get_post_insights",  # GET {post_id}/insights, fixed metrics
        "get_video_publish_status",  # GET {video_id}?fields=status,permalink_url
        "list_page_posts",  # GET {page}/posts, fixed fields
        "list_post_comments",  # GET {post_id}/comments, fixed fields
    },
    "instagram": {
        "get_account_insights",  # GET {ig_user}/insights, fixed metrics
        "get_container_status",  # GET {container}?fields=status_code,status
        "get_media",
        "get_media_insights",  # metric set chosen by a Literal
        "get_profile",
        "list_catalogs",  # GET {ig_user}/available_catalogs
        "list_media",
        "list_media_comments",
        "lookup_business_account",  # business_discovery, username matched against a handle regex
        "search_catalog_products",  # GET {ig_user}/catalog_product_search, q in the query string
    },
    "linkedin": {
        "get_organization_followers",  # networkSizes/{org urn}
        "get_organization_profile",  # organizations/{org id}
        "get_organization_share_statistics",  # organizationalEntityShareStatistics, org pinned
        "get_organization_post",  # posts/{urn}, URN format-checked, author must be the connected org
        "list_organization_posts",  # posts?q=author, org pinned
    },
    "pinterest": {
        "get_pin",
        "get_pin_analytics",
        "get_user_account",
        "get_user_analytics",
        "list_pins",
    },
    "threads": {
        "get_container_status",
        "get_profile",  # GET me, fixed fields
        "get_profile_insights",  # GET me/threads_insights, fixed metrics
        "get_thread",
        "get_thread_insights",
        "list_replies",  # GET {media}/replies, fixed fields
        "list_threads",  # GET me/threads, fixed fields
    },
    "tiktok": {
        "get_user_info",  # GET user/info/, fixed fields
        "list_videos",  # POST video/list/ (a query; nothing created)
        "publish_status_fetch",  # POST post/publish/status/fetch/ (a query)
        "query_videos",  # POST video/query/ (a query)
    },
    "youtube": {
        "get_channel",
        "list_playlist_videos",  # playlistItems.list, page token handed out as next_cursor
        "list_video_comments",  # commentThreads.list, page token handed out as next_cursor
        "list_videos",
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {}

# Opaque pagination cursors and one product search: they only reach a query string.
REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = {
    ("facebook", "list_page_posts", "after"),
    ("facebook", "list_post_comments", "after"),
    ("instagram", "list_media", "after"),
    ("instagram", "list_media_comments", "after"),
    ("instagram", "search_catalog_products", "query"),
    ("pinterest", "list_pins", "bookmark"),
    ("threads", "list_replies", "after"),
    ("threads", "list_threads", "after"),
    ("youtube", "list_playlist_videos", "cursor"),
    ("youtube", "list_video_comments", "cursor"),
}

_GRAPH_GENERIC = {
    "get_object": "any object and any fields (a Page's access_token)",
    "get_edge": "any edge and any fields (me/accounts returns Page tokens)",
    "get_insights": "any object and any metric",
    "post_edge": "POST to any edge",
}

# Public client methods deliberately left without any mark (never offered to an agent).
UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    **{("facebook", m): r for m, r in _GRAPH_GENERIC.items()},
    ("facebook", "post_edge_multipart"): "multipart upload to any edge",
    ("facebook", "upload_hosted_video"): "rupload: Meta fetches an agent URL with the Page token",
    **{("instagram", m): r for m, r in _GRAPH_GENERIC.items()},
    ("instagram", "business_discovery"): "takes any fields; username unchecked in the field expression",
    ("instagram", "available_catalogs"): "takes any IG user id; the agent uses list_catalogs",
    ("instagram", "catalog_product_search"): "takes any IG user id; the agent uses search_catalog_products",
    **{("threads", m): r for m, r in _GRAPH_GENERIC.items()},
    ("linkedin", "get_post"): "any post URN; the agent uses get_organization_post",
    ("linkedin", "get_raw"): "any REST path, and an access_token override",
    ("linkedin", "get_organization"): "any organization; the agent uses get_organization_profile",
    ("linkedin", "get_follower_count"): "any organization; the agent uses get_organization_followers",
    ("linkedin", "list_posts"): "any author; the agent uses list_organization_posts",
    ("linkedin", "get_share_statistics"): "any organization; the agent uses get_organization_share_statistics",
    ("youtube", "list_playlist_items"): "nextPageToken is redacted by BAPP; the agent uses list_playlist_videos",
    ("youtube", "upload_video_init"): "returns a resumable upload session URL (a bearer capability)",
    ("youtube", "upload_video_content"): "PUTs bytes to a URL",
}

NOT_MARKED: dict[str, str] = {
    "meta": "user-token connection that hands out Page tokens (me/accounts); get_ai_client() is None",
}


def test_every_social_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


def test_meta_exposes_no_ai_client():
    assert ai_guard.adapter(FAMILY, "meta").get_ai_client() is None


_CHECKED = [p for p in SOCIAL_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_social_marks(provider, check):
    kwargs = {"free_text": REVIEWED_FREE_TEXT} if check is ai_guard.check_free_text_reviewed else {}
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", _CHECKED)
def test_every_public_method_is_marked_or_left_out_on_purpose(provider):
    """A new public client method fails here until it is marked or listed as unmarked."""
    cls = ai_guard.client_cls(FAMILY, provider)
    marked = set(ai_methods(cls))
    public = {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, (staticmethod, classmethod))
    }
    assert public - marked == {m for p, m in UNMARKED_ON_PURPOSE if p == provider}


@pytest.mark.parametrize("provider", _CHECKED)
def test_no_read_takes_a_host_version_path_or_fields(provider):
    """Host, API version, raw paths, edges and fields come from the client, never from the agent."""
    blocked = {
        "url",
        "next_url",
        "upload_url",
        "host",
        "base_url",
        "version",
        "path",
        "edge",
        "fields",
        "metric",
        "access_token",
        "token",
        "payload",
    }
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        assert not set(inspect.signature(fn).parameters) & blocked, name


@pytest.mark.parametrize("provider", ["facebook", "instagram", "linkedin"])
def test_adapter_pins_the_client_to_the_connected_account(provider):
    client = ai_guard.adapter(FAMILY, provider).get_ai_client()
    attr = {"facebook": "page_id", "instagram": "ig_user_id", "linkedin": "organization_id"}[provider]
    assert getattr(client, attr) == "dummy"


# ── Graph clients: fixed edges and fields, owner checks, no paging URLs ──

_LIST_PAGE = {
    "data": [{"id": "1", "comments": {"data": [], "paging": {"next": "https://graph/x?access_token=SECRET"}}}],
    "paging": {
        "cursors": {"before": "b", "after": "a"},
        "next": "https://graph.facebook.com/v19.0/1/posts?access_token=SECRET&after=a",
        "previous": "https://graph.facebook.com/v19.0/1/posts?access_token=SECRET&before=b",
    },
}


def _graph(cls_path: str, owner: str = "", owner_field: str = "from", **kwargs):
    """A Graph client whose fake HTTP answers single objects with ``{owner_field: {id: owner}}``
    (and ``me`` with ``{"id": owner}``), edges and insights with a list page."""
    module, name = cls_path.rsplit(".", 1)
    cls = getattr(__import__(module, fromlist=[name]), name)
    http = MagicMock()

    def answer(method, path, **kw):
        if "/" in path:
            return _LIST_PAGE
        if path == "me":
            return {"id": owner, "username": "me"}
        return {"id": path, owner_field: {"id": owner}} if owner else {"id": path}

    http.call.side_effect = answer
    return cls(http, **kwargs), http


def _assert_graph_reads(http, expected_paths):
    paths = []
    for call in http.call.call_args_list:
        method, path = call.args[:2]
        assert method == "GET", call
        params = call.kwargs.get("params") or {}
        assert "access_token" not in params, call
        assert "access_token" not in str(params.get("fields", "")), call
        paths.append(path)
    assert paths == expected_paths


_FB = "bapp_connectors.providers.social.facebook.client.FacebookGraphClient"
_IG = "bapp_connectors.providers.social.instagram.client.InstagramGraphClient"
_TH = "bapp_connectors.providers.social.threads.client.ThreadsApiClient"


def test_facebook_reads_use_fixed_edges_and_fields():
    client, http = _graph(_FB, owner="77", page_id="77")
    client.get_page_profile()
    client.list_page_posts(limit=5, after="abc")
    client.get_post_details("77_1")
    client.list_post_comments("77_1")
    client.get_post_insights("77_1")
    client.get_page_insights(since=date(2026, 1, 1), until=date(2026, 1, 31), period="week")
    client.get_video_publish_status("9")
    _assert_graph_reads(
        http, ["77", "77/posts", "77_1", "77_1", "77_1/comments", "77_1", "77_1/insights", "77/insights", "9"]
    )
    insights = http.call.call_args_list[7].kwargs["params"]
    assert insights["period"] == "week"
    assert insights["since"] == 1767225600  # 2026-01-01T00:00:00Z
    assert insights["until"] == 1769903999  # 2026-01-31T23:59:59Z


@pytest.mark.parametrize("post_id", ["88_1", "77", "me", "77_1_2", "77_x", "1_77_1", ""])
@pytest.mark.parametrize("method", ["get_post_details", "list_post_comments", "get_post_insights"])
def test_facebook_refuses_posts_of_another_page_before_any_call(method, post_id):
    client, http = _graph(_FB, owner="77", page_id="77")
    with pytest.raises(ValidationError):
        getattr(client, method)(post_id)
    http.call.assert_not_called()


@pytest.mark.parametrize("method", ["get_post_details", "list_post_comments", "get_post_insights"])
@pytest.mark.parametrize("owner", ["88", ""])
def test_facebook_refuses_a_post_whose_owner_is_not_the_page(method, owner):
    client, http = _graph(_FB, owner=owner, page_id="77")
    with pytest.raises(ValidationError):
        getattr(client, method)("77_1")
    assert all("/" not in c.args[1] for c in http.call.call_args_list)  # no comments/insights call


@pytest.mark.parametrize("video_id", ["me", "debug_token", "9_1", ""])
def test_facebook_video_status_takes_a_numeric_id(video_id):
    client, http = _graph(_FB, owner="77", page_id="77")
    with pytest.raises(ValidationError):
        client.get_video_publish_status(video_id)
    http.call.assert_not_called()


def test_facebook_video_status_refuses_another_pages_video():
    client, _http = _graph(_FB, owner="88", page_id="77")
    with pytest.raises(ValidationError):
        client.get_video_publish_status("9")


def test_graph_reads_drop_paging_urls_everywhere():
    client, _http = _graph(_FB, page_id="77")
    page = client.list_page_posts()
    assert "SECRET" not in repr(page)
    assert page["paging"] == {"cursors": {"before": "b", "after": "a"}, "has_next": True}
    assert page["data"][0]["comments"]["paging"] == {"cursors": {}, "has_next": True}


def test_facebook_reads_need_the_connected_page():
    client, http = _graph(_FB, owner="77")
    for read in (client.list_page_posts, lambda: client.get_video_publish_status("9")):
        with pytest.raises(ValidationError):
            read()
    http.call.assert_not_called()


def test_instagram_reads_use_fixed_edges_and_fields():
    client, http = _graph(_IG, owner="55", owner_field="owner", ig_user_id="55")
    http.call.side_effect = None
    calls = []

    def answer(method, path, **kw):
        calls.append(path)
        if path == "55/available_catalogs":
            return {"data": [{"catalog_id": "9"}]}
        if "/" in path:
            return _LIST_PAGE
        return {"id": path, "owner": {"id": "55"}}

    http.call.side_effect = answer
    client.get_profile()
    client.list_media(after="c")
    client.get_media("1")
    client.list_media_comments("1")
    client.get_media_insights("1", kind="video")
    client.get_account_insights()
    client.get_container_status("3")
    client.list_catalogs()
    client.search_catalog_products("9", "red shoes & x=1")
    _assert_graph_reads(
        http,
        [
            "55",
            "55/media",
            "1",
            "1",
            "1/comments",
            "1",
            "1/insights",
            "55/insights",
            "3",
            "55/available_catalogs",
            "55/available_catalogs",
            "55/catalog_product_search",
        ],
    )
    assert http.call.call_args_list[6].kwargs["params"]["metric"] == "plays,video_views"
    search = http.call.call_args_list[-1].kwargs["params"]
    assert search["q"] == "red shoes & x=1"  # a query value, never a path
    assert search["catalog_id"] == "9"


@pytest.mark.parametrize("method", ["get_media", "list_media_comments", "get_media_insights"])
@pytest.mark.parametrize("owner", ["66", ""])
def test_instagram_refuses_media_of_another_account(method, owner):
    client, http = _graph(_IG, owner=owner, owner_field="owner", ig_user_id="55")
    with pytest.raises(ValidationError):
        getattr(client, method)("1")
    assert all("/" not in c.args[1] for c in http.call.call_args_list)


@pytest.mark.parametrize("method", ["get_media", "list_media_comments", "get_media_insights", "get_container_status"])
@pytest.mark.parametrize("media_id", ["me", "55/media", "1_2", ""])
def test_instagram_ids_are_numeric(method, media_id):
    client, http = _graph(_IG, owner="55", owner_field="owner", ig_user_id="55")
    with pytest.raises(ValidationError):
        getattr(client, method)(media_id)
    http.call.assert_not_called()


def test_instagram_refuses_a_catalog_not_available_to_the_account():
    client, http = _graph(_IG, ig_user_id="55")
    http.call.side_effect = lambda method, path, **kw: {"data": [{"catalog_id": "9"}]}
    with pytest.raises(ValidationError):
        client.search_catalog_products("10", "shoes")
    assert [c.args[1] for c in http.call.call_args_list] == ["55/available_catalogs"]


@pytest.mark.parametrize("username", ["acme){access_token}", "a,access_token", "a b", "", "x" * 31])
def test_instagram_lookup_refuses_anything_but_a_handle(username):
    client, http = _graph(_IG, ig_user_id="55")
    with pytest.raises(ValidationError):
        client.lookup_business_account(username)
    http.call.assert_not_called()


def test_instagram_lookup_uses_fixed_fields():
    client, http = _graph(_IG, ig_user_id="55")
    client.lookup_business_account("@acme.shop")
    path, params = http.call.call_args.args[1], http.call.call_args.kwargs["params"]
    assert path == "55"
    assert params["fields"].startswith("business_discovery.username(acme.shop){")
    assert "access_token" not in params["fields"]


def test_threads_reads_use_fixed_edges_and_fields():
    client, http = _graph(_TH, owner="5", owner_field="owner")
    client.get_profile()
    client.list_threads(limit=3)
    client.get_thread("1")
    client.list_replies("1", after="z")
    client.get_thread_insights("1")
    client.get_profile_insights(since=date(2026, 2, 1))
    client.get_container_status("2")
    _assert_graph_reads(
        http,
        ["me", "me/threads", "1", "me", "1", "1/replies", "1", "1/insights", "me/threads_insights", "2"],
    )


@pytest.mark.parametrize("method", ["get_thread", "list_replies", "get_thread_insights"])
def test_threads_refuses_media_of_another_user(method):
    client, http = _graph(_TH, owner="5", owner_field="owner")
    http.call.side_effect = lambda m, path, **kw: {"id": "5"} if path == "me" else {"id": path, "owner": {"id": "6"}}
    with pytest.raises(ValidationError):
        getattr(client, method)("1")
    assert all("/" not in c.args[1] for c in http.call.call_args_list)


@pytest.mark.parametrize("method", ["get_thread", "list_replies", "get_thread_insights", "get_container_status"])
def test_threads_ids_are_numeric(method):
    client, http = _graph(_TH, owner="5", owner_field="owner")
    with pytest.raises(ValidationError):
        getattr(client, method)("me")
    http.call.assert_not_called()


# ── LinkedIn: pinned to the connected organization ──


def _linkedin(response=None, organization_id="42"):
    from bapp_connectors.providers.social.linkedin.client import LinkedInApiClient

    http = MagicMock()
    http.call.return_value = response if response is not None else {}
    return LinkedInApiClient(http, access_token="t", version="202405", organization_id=organization_id), http


def test_linkedin_org_reads_are_pinned():
    client, http = _linkedin()
    client.get_organization_profile()
    client.get_organization_followers()
    client.list_organization_posts(count=10, start=20)
    client.get_organization_share_statistics(["urn:li:share:1"])
    paths = [c.args[1] for c in http.call.call_args_list]
    assert paths[0] == "organizations/42"
    assert paths[1].startswith("networkSizes/urn%3Ali%3Aorganization%3A42?")
    assert paths[2] == "posts?q=author&author=urn%3Ali%3Aorganization%3A42&count=10&start=20"
    assert "organizationalEntity=urn%3Ali%3Aorganization%3A42" in paths[3]
    assert "shares[0]=urn%3Ali%3Ashare%3A1" in paths[3]


@pytest.mark.parametrize("urn", ["urn:li:share:1&x=1", "urn:li:organization:42", "1", ""])
def test_linkedin_share_statistics_refuse_a_non_post_urn(urn):
    client, http = _linkedin()
    with pytest.raises(ValidationError):
        client.get_organization_share_statistics([urn])
    http.call.assert_not_called()


def test_linkedin_post_of_the_organization():
    client, http = _linkedin({"id": "urn:li:share:7", "author": "urn:li:organization:42"})
    assert client.get_organization_post("urn:li:share:7")["id"] == "urn:li:share:7"
    assert http.call.call_args.args[1] == "posts/urn%3Ali%3Ashare%3A7"


@pytest.mark.parametrize("author", ["urn:li:organization:43", "urn:li:person:42", None])
def test_linkedin_post_of_another_author_is_refused(author):
    client, _http = _linkedin({"id": "urn:li:ugcPost:7", "author": author})
    with pytest.raises(ValidationError):
        client.get_organization_post("urn:li:ugcPost:7")


@pytest.mark.parametrize("urn", ["urn:li:share:7&x=1", "urn:li:activity:7", "7", ""])
def test_linkedin_post_urn_format_is_checked_before_any_call(urn):
    client, http = _linkedin()
    with pytest.raises(ValidationError):
        client.get_organization_post(urn)
    http.call.assert_not_called()


def test_linkedin_org_reads_need_the_organization():
    client, http = _linkedin(organization_id="")
    for read in (client.list_organization_posts, lambda: client.get_organization_post("urn:li:share:1")):
        with pytest.raises(ValidationError):
            read()
    http.call.assert_not_called()


# ── Pinterest: path ids ──


@pytest.mark.parametrize("pin_id", ["1/../user_account", "1?x=1", "a b", ""])
def test_pinterest_pin_ids_are_checked(pin_id):
    from bapp_connectors.providers.social.pinterest.client import PinterestApiClient

    http = MagicMock()
    client = PinterestApiClient(http)
    with pytest.raises(ValidationError):
        client.get_pin(pin_id)
    with pytest.raises(ValidationError):
        client.get_pin_analytics(pin_id, "2026-01-01", "2026-01-31", ["IMPRESSION"])
    http.call.assert_not_called()


# ── YouTube: page tokens handed out under a key BAPP does not redact ──


def test_youtube_pages_rename_the_page_token():
    from bapp_connectors.providers.social.youtube.client import YouTubeApiClient

    http = MagicMock()
    http.call.return_value = {"items": [{"id": "v"}], "nextPageToken": "NEXT", "prevPageToken": "PREV"}
    client = YouTubeApiClient(http, api_key="k" * 20)
    page = client.list_video_comments("vid1", cursor="CUR")
    assert page == {"items": [{"id": "v"}], "next_cursor": "NEXT", "prev_cursor": "PREV"}
    call = http.call.call_args
    assert call.args[:2] == ("GET", "commentThreads")
    assert call.kwargs["params"]["videoId"] == "vid1"
    assert call.kwargs["params"]["pageToken"] == "CUR"
    page = client.list_playlist_videos("UU1")
    assert page["next_cursor"] == "NEXT"
    assert http.call.call_args.args[1] == "playlistItems"


@pytest.mark.parametrize("bad", ["a,b", "a/b", "a b", ""])
def test_youtube_ids_are_checked(bad):
    from bapp_connectors.providers.social.youtube.client import YouTubeApiClient

    http = MagicMock()
    client = YouTubeApiClient(http, api_key="k" * 20)
    for read in (
        lambda: client.get_channel(bad or "x y"),
        lambda: client.list_videos(["ok", bad]),
        lambda: client.list_playlist_videos(bad),
        lambda: client.list_video_comments(bad),
    ):
        with pytest.raises(ValidationError):
            read()
    http.call.assert_not_called()
