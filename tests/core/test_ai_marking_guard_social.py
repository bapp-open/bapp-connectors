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
        "get_post",  # posts/{urn}, URN percent-encoded
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


# ── Graph clients: fixed edges and fields, no paging URLs ──


def _graph(cls_path: str, **kwargs):
    module, name = cls_path.rsplit(".", 1)
    cls = getattr(__import__(module, fromlist=[name]), name)
    http = MagicMock()
    http.call.return_value = {
        "data": [{"id": "1", "comments": {"data": [], "paging": {"next": "https://graph/x?access_token=SECRET"}}}],
        "paging": {
            "cursors": {"before": "b", "after": "a"},
            "next": "https://graph.facebook.com/v19.0/1/posts?access_token=SECRET&after=a",
            "previous": "https://graph.facebook.com/v19.0/1/posts?access_token=SECRET&before=b",
        },
    }
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


def test_facebook_reads_use_fixed_edges_and_fields():
    client, http = _graph("bapp_connectors.providers.social.facebook.client.FacebookGraphClient", page_id="77")
    client.get_page_profile()
    client.list_page_posts(limit=5, after="abc")
    client.get_post_details("77_1")
    client.list_post_comments("77_1")
    client.get_post_insights("77_1")
    client.get_page_insights(since=date(2026, 1, 1), until=date(2026, 1, 31), period="week")
    client.get_video_publish_status("9")
    _assert_graph_reads(http, ["77", "77/posts", "77_1", "77_1/comments", "77_1/insights", "77/insights", "9"])
    insights = http.call.call_args_list[5].kwargs["params"]
    assert insights["period"] == "week"
    assert insights["since"] == 1767225600  # 2026-01-01T00:00:00Z
    assert insights["until"] == 1769903999  # 2026-01-31T23:59:59Z


def test_graph_reads_drop_paging_urls_everywhere():
    client, _http = _graph("bapp_connectors.providers.social.facebook.client.FacebookGraphClient", page_id="77")
    page = client.list_page_posts()
    assert "SECRET" not in repr(page)
    assert page["paging"] == {"cursors": {"before": "b", "after": "a"}, "has_next": True}
    assert page["data"][0]["comments"]["paging"] == {"cursors": {}, "has_next": True}


def test_facebook_reads_need_the_connected_page():
    client, http = _graph("bapp_connectors.providers.social.facebook.client.FacebookGraphClient")
    with pytest.raises(ValidationError):
        client.list_page_posts()
    http.call.assert_not_called()


def test_instagram_reads_use_fixed_edges_and_fields():
    client, http = _graph("bapp_connectors.providers.social.instagram.client.InstagramGraphClient", ig_user_id="55")
    client.get_profile()
    client.list_media(after="c")
    client.get_media("m1")
    client.list_media_comments("m1")
    client.get_media_insights("m1", kind="video")
    client.get_account_insights()
    client.get_container_status("c1")
    client.list_catalogs()
    client.search_catalog_products("cat9", "red shoes & x=1")
    _assert_graph_reads(
        http,
        [
            "55",
            "55/media",
            "m1",
            "m1/comments",
            "m1/insights",
            "55/insights",
            "c1",
            "55/available_catalogs",
            "55/catalog_product_search",
        ],
    )
    assert http.call.call_args_list[4].kwargs["params"]["metric"] == "plays,video_views"
    search = http.call.call_args_list[-1].kwargs["params"]
    assert search["q"] == "red shoes & x=1"  # a query value, never a path
    assert search["catalog_id"] == "cat9"


@pytest.mark.parametrize("username", ["acme){access_token}", "a,access_token", "a b", "", "x" * 31])
def test_instagram_lookup_refuses_anything_but_a_handle(username):
    client, http = _graph("bapp_connectors.providers.social.instagram.client.InstagramGraphClient", ig_user_id="55")
    with pytest.raises(ValidationError):
        client.lookup_business_account(username)
    http.call.assert_not_called()


def test_instagram_lookup_uses_fixed_fields():
    client, http = _graph("bapp_connectors.providers.social.instagram.client.InstagramGraphClient", ig_user_id="55")
    client.lookup_business_account("@acme.shop")
    path, params = http.call.call_args.args[1], http.call.call_args.kwargs["params"]
    assert path == "55"
    assert params["fields"].startswith("business_discovery.username(acme.shop){")
    assert "access_token" not in params["fields"]


def test_threads_reads_use_fixed_edges_and_fields():
    client, http = _graph("bapp_connectors.providers.social.threads.client.ThreadsApiClient")
    client.get_profile()
    client.list_threads(limit=3)
    client.get_thread("t1")
    client.list_replies("t1", after="z")
    client.get_thread_insights("t1")
    client.get_profile_insights(since=date(2026, 2, 1))
    client.get_container_status("c1")
    _assert_graph_reads(http, ["me", "me/threads", "t1", "t1/replies", "t1/insights", "me/threads_insights", "c1"])


# ── LinkedIn: pinned to the connected organization ──


def test_linkedin_org_reads_are_pinned():
    from bapp_connectors.providers.social.linkedin.client import LinkedInApiClient

    http = MagicMock()
    http.call.return_value = {}
    client = LinkedInApiClient(http, access_token="t", version="202405", organization_id="42")
    client.get_organization_profile()
    client.get_organization_followers()
    client.list_organization_posts(count=10, start=20)
    client.get_organization_share_statistics(["urn:li:share:1&x=1"])
    paths = [c.args[1] for c in http.call.call_args_list]
    assert paths[0] == "organizations/42"
    assert paths[1].startswith("networkSizes/urn%3Ali%3Aorganization%3A42?")
    assert paths[2] == "posts?q=author&author=urn%3Ali%3Aorganization%3A42&count=10&start=20"
    assert "organizationalEntity=urn%3Ali%3Aorganization%3A42" in paths[3]
    assert "&x=1" not in paths[3]  # share URNs are percent-encoded


def test_linkedin_org_reads_need_the_organization():
    from bapp_connectors.providers.social.linkedin.client import LinkedInApiClient

    http = MagicMock()
    client = LinkedInApiClient(http, access_token="t", version="202405")
    with pytest.raises(ValidationError):
        client.list_organization_posts()
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
