"""
YouTube Shorts social adapter unit tests + contract tests.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto.social import SocialMediaType
from bapp_connectors.providers.social.youtube.adapter import YouTubeSocialAdapter
from bapp_connectors.providers.social.youtube.mappers import parse_iso8601_duration
from tests.fake_http import FakeHttpClient
from tests.social.contract import SocialContractTests

CHANNEL_ID = "UC1234567890abcdefghij"
UPLOADS_PLAYLIST_ID = "UU1234567890abcdefghij"
SHORT_VIDEO_ID = "short45sec1"
LONG_VIDEO_ID = "long10min01"

CHANNELS_RESPONSE = {
    "kind": "youtube#channelListResponse",
    "items": [
        {
            "kind": "youtube#channel",
            "id": CHANNEL_ID,
            "snippet": {
                "title": "Test Channel",
                "description": "A channel for testing #shorts",
                "customUrl": "@testchannel",
                "publishedAt": "2020-01-15T09:00:00Z",
                "thumbnails": {
                    "default": {"url": "https://yt.img/default.jpg", "width": 88, "height": 88},
                    "high": {"url": "https://yt.img/high.jpg", "width": 800, "height": 800},
                },
            },
            "statistics": {
                "viewCount": "123456",
                "subscriberCount": "1200",
                "hiddenSubscriberCount": False,
                "videoCount": "2",
            },
            "contentDetails": {
                "relatedPlaylists": {"likes": "", "uploads": UPLOADS_PLAYLIST_ID},
            },
        },
    ],
}

PLAYLIST_ITEMS_RESPONSE = {
    "kind": "youtube#playlistItemListResponse",
    "items": [
        {
            "kind": "youtube#playlistItem",
            "snippet": {"title": "My first Short", "playlistId": UPLOADS_PLAYLIST_ID, "position": 0},
            "contentDetails": {"videoId": SHORT_VIDEO_ID},
        },
        {
            "kind": "youtube#playlistItem",
            "snippet": {"title": "A long tutorial", "playlistId": UPLOADS_PLAYLIST_ID, "position": 1},
            "contentDetails": {"videoId": LONG_VIDEO_ID},
        },
    ],
}

VIDEOS = {
    SHORT_VIDEO_ID: {
        "kind": "youtube#video",
        "id": SHORT_VIDEO_ID,
        "snippet": {
            "title": "My first Short #shorts",
            "description": "Quick tip! #Shorts #Tips",
            "channelId": CHANNEL_ID,
            "publishedAt": "2024-05-01T10:00:00Z",
            "thumbnails": {
                "default": {"url": "https://yt.img/short-default.jpg"},
                "maxres": {"url": "https://yt.img/short-maxres.jpg"},
            },
        },
        "statistics": {"viewCount": "1000", "likeCount": "100", "commentCount": "10"},
        "contentDetails": {"duration": "PT45S"},
    },
    LONG_VIDEO_ID: {
        "kind": "youtube#video",
        "id": LONG_VIDEO_ID,
        "snippet": {
            "title": "A long tutorial",
            "description": "Full walkthrough.",
            "channelId": CHANNEL_ID,
            "publishedAt": "2024-04-20T08:30:00Z",
            "thumbnails": {"high": {"url": "https://yt.img/long-high.jpg"}},
        },
        "statistics": {"viewCount": "5000", "likeCount": "250", "commentCount": "40"},
        "contentDetails": {"duration": "PT10M3S"},
    },
}


def _videos_response(method, path, kwargs):
    """Return only the videos requested via the ``id`` query parameter."""
    requested = (kwargs.get("params") or {}).get("id", "").split(",")
    return {
        "kind": "youtube#videoListResponse",
        "items": [VIDEOS[vid] for vid in requested if vid in VIDEOS],
    }


def make_fake_http() -> FakeHttpClient:
    fake = FakeHttpClient()
    fake.add("GET", "channels", CHANNELS_RESPONSE)
    fake.add("GET", "playlistItems", PLAYLIST_ITEMS_RESPONSE)
    fake.add("GET", "videos", _videos_response)
    return fake


def make_adapter(credentials: dict | None = None, config: dict | None = None) -> YouTubeSocialAdapter:
    return YouTubeSocialAdapter(
        credentials=credentials if credentials is not None else {"api_key": "test-key"},
        http_client=make_fake_http(),
        config=config if config is not None else {"channel_id": CHANNEL_ID},
    )


class TestYouTubeContract(SocialContractTests):
    """Run all social contract tests for YouTube."""

    @pytest.fixture
    def adapter(self) -> YouTubeSocialAdapter:
        return make_adapter()

    @pytest.fixture
    def sample_post_id(self) -> str:
        return SHORT_VIDEO_ID


class TestDurationParser:
    """ISO 8601 duration parsing."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("PT45S", 45.0),
            ("PT1M30S", 90.0),
            ("PT1H2M3S", 3723.0),
            ("P0D", 0.0),
        ],
    )
    def test_parse(self, value: str, expected: float):
        assert parse_iso8601_duration(value) == expected


class TestYouTubeAdapter:
    """YouTube-specific adapter tests."""

    def test_shorts_only_filters_long_videos(self):
        adapter = make_adapter()
        result = adapter.list_posts(limit=5)
        ids = [post.id for post in result.items]
        assert ids == [SHORT_VIDEO_ID]
        assert result.items[0].media_type == SocialMediaType.SHORT_VIDEO

    def test_shorts_only_false_includes_long_videos(self):
        adapter = make_adapter(config={"channel_id": CHANNEL_ID, "shorts_only": "false"})
        result = adapter.list_posts(limit=5)
        ids = [post.id for post in result.items]
        assert ids == [SHORT_VIDEO_ID, LONG_VIDEO_ID]
        by_id = {post.id: post for post in result.items}
        assert by_id[SHORT_VIDEO_ID].media_type == SocialMediaType.SHORT_VIDEO
        assert by_id[LONG_VIDEO_ID].media_type == SocialMediaType.VIDEO

    def test_api_key_goes_into_query_params(self):
        fake = make_fake_http()
        adapter = YouTubeSocialAdapter(
            credentials={"api_key": "test-key"},
            http_client=fake,
            config={"channel_id": CHANNEL_ID},
        )
        adapter.get_account()
        call = fake.last_call()
        assert call.kwargs["params"]["key"] == "test-key"
        assert call.kwargs["params"]["id"] == CHANNEL_ID
        assert call.kwargs["headers"] is None

    def test_access_token_goes_into_authorization_header(self):
        fake = make_fake_http()
        adapter = YouTubeSocialAdapter(
            credentials={"access_token": "test-token"},
            http_client=fake,
            config={},
        )
        adapter.get_account()
        call = fake.last_call()
        assert call.kwargs["headers"] == {"Authorization": "Bearer test-token"}
        assert "key" not in call.kwargs["params"]
        assert call.kwargs["params"]["mine"] == "true"

    def test_validate_credentials_requires_api_key_or_access_token(self):
        adapter = make_adapter(credentials={}, config={"channel_id": CHANNEL_ID})
        assert adapter.validate_credentials() is False

    def test_validate_credentials_api_key_requires_channel_id(self):
        adapter = make_adapter(credentials={"api_key": "test-key"}, config={})
        assert adapter.validate_credentials() is False

    def test_validate_credentials_access_token_alone_is_enough(self):
        adapter = make_adapter(credentials={"access_token": "test-token"}, config={})
        assert adapter.validate_credentials() is True

    def test_stats_mapping(self):
        adapter = make_adapter()
        stats = adapter.get_post_stats(SHORT_VIDEO_ID)
        assert stats.post_id == SHORT_VIDEO_ID
        assert stats.views == 1000
        assert stats.likes == 100
        assert stats.comments == 10
        assert stats.shares is None
        assert stats.engagement_rate == pytest.approx((100 + 10) / 1000)

    def test_account_mapping(self):
        adapter = make_adapter()
        account = adapter.get_account()
        assert account.id == CHANNEL_ID
        assert account.username == "@testchannel"
        assert account.profile_url == "https://www.youtube.com/@testchannel"
        assert account.avatar_url == "https://yt.img/high.jpg"
        assert account.followers_count == 1200
        assert account.posts_count == 2
        assert account.extra["uploads_playlist_id"] == UPLOADS_PLAYLIST_ID

    def test_account_stats(self):
        adapter = make_adapter()
        stats = adapter.get_account_stats()
        assert stats.account_id == CHANNEL_ID
        assert stats.followers_count == 1200
        assert stats.posts_count == 2
        assert stats.total_views == 123456

    def test_post_hashtags_and_metadata(self):
        adapter = make_adapter()
        post = adapter.get_post(SHORT_VIDEO_ID)
        assert post.url == f"https://www.youtube.com/watch?v={SHORT_VIDEO_ID}"
        assert post.duration_seconds == 45.0
        assert post.thumbnail_url == "https://yt.img/short-maxres.jpg"
        assert post.hashtags == ["#shorts", "#tips"]
        assert post.published_at is not None
        assert post.published_at.year == 2024

    def test_test_connection_reports_channel_title(self):
        adapter = make_adapter()
        result = adapter.test_connection()
        assert result.success is True
        assert "Test Channel" in result.message
