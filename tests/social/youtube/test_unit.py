"""
YouTube Shorts social adapter unit tests + contract tests.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.dto.social import (
    PublishStatus,
    SocialMediaType,
    SocialPostDraft,
    SocialPrivacy,
)
from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ValidationError
from bapp_connectors.providers.social.youtube.adapter import YouTubeSocialAdapter
from bapp_connectors.providers.social.youtube.client import UPLOAD_URL
from bapp_connectors.providers.social.youtube.manifest import manifest
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


# ── Publishing ──

UPLOAD_SESSION_URL = "https://upload.example/session1"
UPLOADED_VIDEO_ID = "vid123"


class FakeResponse:
    """Minimal stand-in for requests.Response as consumed by upload_video_init."""

    def __init__(self, ok: bool = True, headers: dict | None = None, status_code: int = 200):
        self.ok = ok
        self.headers = headers or {}
        self.status_code = status_code


def make_publish_fake() -> FakeHttpClient:
    fake = make_fake_http()
    fake.add(
        "POST",
        "upload/youtube/v3/videos",
        lambda method, path, kwargs: FakeResponse(headers={"Location": UPLOAD_SESSION_URL}),
    )
    fake.add(
        "PUT",
        "upload.example/session1",
        {"id": UPLOADED_VIDEO_ID, "status": {"uploadStatus": "uploaded"}},
    )
    return fake


def make_publish_adapter(credentials: dict | None = None) -> tuple[YouTubeSocialAdapter, FakeHttpClient]:
    fake = make_publish_fake()
    adapter = YouTubeSocialAdapter(
        credentials=credentials if credentials is not None else {"access_token": "test-token"},
        http_client=fake,
        config={},
    )
    return adapter, fake


def make_draft(**overrides) -> SocialPostDraft:
    fields: dict = {
        "title": "My Short",
        "description": "A quick clip #shorts",
        "media_type": SocialMediaType.SHORT_VIDEO,
        "content": b"fake-video-bytes",
        "privacy": SocialPrivacy.UNLISTED,
        "tags": ["shorts", "tips"],
    }
    fields.update(overrides)
    return SocialPostDraft(**fields)


class TestYouTubePublish:
    """publish_post — resumable videos.insert upload."""

    def test_publish_post_uploads_and_returns_published_result(self):
        adapter, fake = make_publish_adapter()
        result = adapter.publish_post(make_draft())

        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == UPLOADED_VIDEO_ID
        assert result.publish_id == UPLOADED_VIDEO_ID
        assert result.url == f"https://www.youtube.com/watch?v={UPLOADED_VIDEO_ID}"
        assert result.extra["upload_status"] == "uploaded"

        init_call, put_call = fake.calls[-2], fake.calls[-1]
        assert init_call.method == "POST"
        assert init_call.path == UPLOAD_URL
        assert init_call.kwargs["params"] == {"uploadType": "resumable", "part": "snippet,status"}
        assert init_call.kwargs["headers"] == {"Authorization": "Bearer test-token"}
        metadata = init_call.kwargs["json"]
        assert metadata["snippet"]["title"] == "My Short"
        assert metadata["snippet"]["description"] == "A quick clip #shorts"
        assert metadata["snippet"]["tags"] == ["shorts", "tips"]
        assert metadata["status"]["privacyStatus"] == "unlisted"
        assert metadata["status"]["selfDeclaredMadeForKids"] is False

        assert put_call.method == "PUT"
        assert put_call.path == UPLOAD_SESSION_URL
        assert put_call.kwargs["data"] == b"fake-video-bytes"
        assert put_call.kwargs["headers"]["Content-Type"] == "video/*"
        assert put_call.kwargs["headers"]["Authorization"] == "Bearer test-token"

    def test_publish_post_reads_file_path(self, tmp_path):
        video_file = tmp_path / "clip.mp4"
        video_file.write_bytes(b"file-bytes")
        adapter, fake = make_publish_adapter()
        result = adapter.publish_post(make_draft(content=None, file_path=str(video_file)))
        assert result.post_id == UPLOADED_VIDEO_ID
        assert fake.last_call().kwargs["data"] == b"file-bytes"

    def test_publish_post_maps_category_id_and_made_for_kids(self):
        adapter, fake = make_publish_adapter()
        adapter.publish_post(make_draft(extra={"category_id": "22", "made_for_kids": True}))
        metadata = fake.calls[-2].kwargs["json"]
        assert metadata["snippet"]["categoryId"] == "22"
        assert metadata["status"]["selfDeclaredMadeForKids"] is True

    def test_publish_post_without_access_token_raises_authentication_error(self):
        adapter, _ = make_publish_adapter(credentials={"api_key": "test-key"})
        with pytest.raises(AuthenticationError):
            adapter.publish_post(make_draft())

    def test_publish_post_with_only_media_url_raises_validation_error(self):
        adapter, _ = make_publish_adapter()
        with pytest.raises(ValidationError, match="media_url"):
            adapter.publish_post(make_draft(content=None, media_url="https://cdn.example/clip.mp4"))

    def test_publish_post_image_media_type_raises_validation_error(self):
        adapter, _ = make_publish_adapter()
        with pytest.raises(ValidationError):
            adapter.publish_post(make_draft(media_type=SocialMediaType.IMAGE))

    def test_supports_social_publish_capability(self):
        adapter = make_adapter()
        assert adapter.supports(SocialPublishCapability) is True


class TestYouTubeCheckPublishStatus:
    """check_publish_status — uploadStatus mapping."""

    @staticmethod
    def make_status_adapter(video: dict | None) -> YouTubeSocialAdapter:
        fake = FakeHttpClient()
        fake.add("GET", "videos", {"items": [video] if video else []})
        return YouTubeSocialAdapter(
            credentials={"access_token": "test-token"},
            http_client=fake,
            config={},
        )

    def test_processed_is_published(self):
        adapter = self.make_status_adapter(
            {"id": UPLOADED_VIDEO_ID, "status": {"uploadStatus": "processed"}, "statistics": {"viewCount": "0"}}
        )
        result = adapter.check_publish_status(UPLOADED_VIDEO_ID)
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == UPLOADED_VIDEO_ID
        assert result.url == f"https://www.youtube.com/watch?v={UPLOADED_VIDEO_ID}"
        assert result.error == ""

    def test_failed_maps_failure_reason(self):
        adapter = self.make_status_adapter(
            {"id": UPLOADED_VIDEO_ID, "status": {"uploadStatus": "failed", "failureReason": "codec"}}
        )
        result = adapter.check_publish_status(UPLOADED_VIDEO_ID)
        assert result.status == PublishStatus.FAILED
        assert result.error == "codec"

    def test_rejected_maps_rejection_reason(self):
        adapter = self.make_status_adapter(
            {"id": UPLOADED_VIDEO_ID, "status": {"uploadStatus": "rejected", "rejectionReason": "duplicate"}}
        )
        result = adapter.check_publish_status(UPLOADED_VIDEO_ID)
        assert result.status == PublishStatus.FAILED
        assert result.error == "duplicate"

    def test_uploaded_is_still_processing(self):
        adapter = self.make_status_adapter({"id": UPLOADED_VIDEO_ID, "status": {"uploadStatus": "uploaded"}})
        result = adapter.check_publish_status(UPLOADED_VIDEO_ID)
        assert result.status == PublishStatus.PROCESSING

    def test_unknown_video_id_raises_permanent_error(self):
        adapter = self.make_status_adapter(None)
        with pytest.raises(PermanentProviderError):
            adapter.check_publish_status("nope1234567")


# ── OAuth ──

OAUTH_CREDENTIALS = {"client_id": "test_client_id", "client_secret": "test_client_secret"}

TOKEN_RESPONSE = {
    "access_token": "new-access-token",
    "refresh_token": "new-refresh-token",
    "expires_in": 3599,
    "token_type": "Bearer",
}


def make_oauth_adapter(token_response: dict | None = None) -> tuple[YouTubeSocialAdapter, FakeHttpClient]:
    fake = FakeHttpClient()
    fake.add("POST", "oauth2.googleapis.com/token", token_response or dict(TOKEN_RESPONSE))
    adapter = YouTubeSocialAdapter(credentials=dict(OAUTH_CREDENTIALS), http_client=fake, config={})
    return adapter, fake


class TestYouTubeOAuth:
    """OAuthCapability: authorization URL, code exchange, token refresh."""

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with YouTube"
        assert len(manifest.auth.oauth.credential_fields) == 2
        assert manifest.auth.oauth.scopes == [
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/youtube.upload",
        ]

    def test_get_authorize_url(self):
        adapter, _ = make_oauth_adapter()
        url = adapter.get_authorize_url("https://example.com/callback", state="abc123")
        assert "accounts.google.com" in url
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=abc123" in url
        assert "access_type=offline" in url

    def test_exchange_code_for_token(self):
        adapter, fake = make_oauth_adapter()
        tokens = adapter.exchange_code_for_token("auth-code", "https://example.com/callback")

        call = fake.last_call()
        assert call.method == "POST"
        assert "oauth2.googleapis.com/token" in call.path
        assert call.kwargs["data"] == {
            "code": "auth-code",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "https://example.com/callback",
            "grant_type": "authorization_code",
        }
        assert tokens.access_token == "new-access-token"
        assert tokens.refresh_token == "new-refresh-token"
        assert tokens.expires_in == 3599
        assert tokens.extra["credentials"] == {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        }

    def test_refresh_token(self):
        adapter, fake = make_oauth_adapter(
            {"access_token": "refreshed-access-token", "expires_in": 3599, "token_type": "Bearer"}
        )
        tokens = adapter.refresh_token("old-refresh-token")

        call = fake.last_call()
        assert call.method == "POST"
        assert call.kwargs["data"] == {
            "refresh_token": "old-refresh-token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "grant_type": "refresh_token",
        }
        assert tokens.access_token == "refreshed-access-token"
        assert tokens.refresh_token == "old-refresh-token"
        assert tokens.extra["credentials"]["access_token"] == "refreshed-access-token"
        assert tokens.extra["credentials"]["refresh_token"] == "old-refresh-token"

    def test_adapter_constructible_with_only_client_credentials(self):
        adapter, _ = make_oauth_adapter()
        assert adapter._client_id == "test_client_id"
        assert adapter._client_secret == "test_client_secret"
        assert adapter.validate_credentials() is True

    def test_supports_oauth_capability(self):
        adapter = make_adapter()
        assert adapter.supports(OAuthCapability) is True
