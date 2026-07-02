"""
TikTok social adapter unit tests + contract tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bapp_connectors.core.capabilities import SocialPublishCapability
from bapp_connectors.core.dto.social import (
    PublishStatus,
    SocialMediaType,
    SocialPostDraft,
    SocialPrivacy,
)
from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    ValidationError,
)
from bapp_connectors.providers.social.tiktok.adapter import TikTokSocialAdapter
from bapp_connectors.providers.social.tiktok.errors import check_response
from bapp_connectors.providers.social.tiktok.mappers import (
    account_from_tiktok,
    account_stats_from_tiktok,
    draft_to_post_info,
    post_from_tiktok,
    post_stats_from_tiktok,
    publish_result_from_status,
)
from tests.fake_http import FakeHttpClient
from tests.social.contract import SocialContractTests

OK_ERROR = {"code": "ok", "message": "", "log_id": "20260702123456789ABCDEF"}

SAMPLE_USER = {
    "open_id": "open-id-abc123",
    "union_id": "union-id-def456",
    "avatar_url": "https://p16-sign.tiktokcdn-us.com/avatar.jpeg",
    "display_name": "CB Soft",
    "username": "cbsoft",
    "bio_description": "Building connectors. #dev",
    "profile_deep_link": "https://www.tiktok.com/@cbsoft",
    "is_verified": True,
    "follower_count": 1200,
    "following_count": 35,
    "likes_count": 56000,
    "video_count": 42,
}

SAMPLE_VIDEO = {
    "id": "7345678901234567890",
    "title": "Ports and adapters in 60s #python",
    "video_description": "Quick tour of our connector framework #Python #CleanArchitecture",
    "create_time": 1719900000,
    "cover_image_url": "https://p16-sign.tiktokcdn-us.com/cover1.jpeg",
    "share_url": "https://www.tiktok.com/@cbsoft/video/7345678901234567890",
    "duration": 58,
    "view_count": 10000,
    "like_count": 800,
    "comment_count": 150,
    "share_count": 50,
    "embed_link": "https://www.tiktok.com/embed/v2/7345678901234567890",
}

SAMPLE_VIDEO_2 = {
    "id": "7345678901234567891",
    "title": "Retry with exponential backoff",
    "video_description": "Never hammer an API again #python #httpx",
    "create_time": 1719813600,
    "cover_image_url": "https://p16-sign.tiktokcdn-us.com/cover2.jpeg",
    "share_url": "https://www.tiktok.com/@cbsoft/video/7345678901234567891",
    "duration": 45,
    "view_count": 5000,
    "like_count": 300,
    "comment_count": 40,
    "share_count": 10,
    "embed_link": "https://www.tiktok.com/embed/v2/7345678901234567891",
}

USER_INFO_RESPONSE = {"data": {"user": SAMPLE_USER}, "error": OK_ERROR}
VIDEO_LIST_RESPONSE = {
    "data": {"videos": [SAMPLE_VIDEO, SAMPLE_VIDEO_2], "cursor": 1719813600, "has_more": True},
    "error": OK_ERROR,
}
VIDEO_QUERY_RESPONSE = {"data": {"videos": [SAMPLE_VIDEO]}, "error": OK_ERROR}


@pytest.fixture
def sample_post_id() -> str:
    return SAMPLE_VIDEO["id"]


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient(base_url="https://open.tiktokapis.com/v2/")
    fake.add("GET", "user/info/", USER_INFO_RESPONSE)
    fake.add("POST", "video/list/", VIDEO_LIST_RESPONSE)
    fake.add("POST", "video/query/", VIDEO_QUERY_RESPONSE)
    return fake


@pytest.fixture
def adapter(fake_http) -> TikTokSocialAdapter:
    return TikTokSocialAdapter(credentials={"token": "test-token"}, http_client=fake_http)


class TestTikTokContract(SocialContractTests):
    """Run all social contract tests for TikTok."""

    @pytest.fixture
    def adapter(self, fake_http) -> TikTokSocialAdapter:
        return TikTokSocialAdapter(credentials={"token": "test-token"}, http_client=fake_http)


class TestTikTokMappers:
    """TikTok-specific mapper tests."""

    def test_account_mapping(self):
        account = account_from_tiktok(SAMPLE_USER)
        assert account.id == "open-id-abc123"
        assert account.username == "cbsoft"
        assert account.display_name == "CB Soft"
        assert account.profile_url == "https://www.tiktok.com/@cbsoft"
        assert account.description == "Building connectors. #dev"
        assert account.followers_count == 1200
        assert account.following_count == 35
        assert account.posts_count == 42
        assert account.is_verified is True

    def test_post_mapping(self):
        post = post_from_tiktok(SAMPLE_VIDEO)
        assert post.id == SAMPLE_VIDEO["id"]
        assert post.media_type == SocialMediaType.SHORT_VIDEO
        assert post.url == SAMPLE_VIDEO["share_url"]
        assert post.title == SAMPLE_VIDEO["title"]
        assert post.description == SAMPLE_VIDEO["video_description"]
        assert post.thumbnail_url == SAMPLE_VIDEO["cover_image_url"]
        assert post.duration_seconds == 58.0
        assert post.published_at == datetime.fromtimestamp(1719900000, tz=UTC)
        assert post.published_at.tzinfo is UTC

    def test_post_stats_fields(self):
        stats = post_stats_from_tiktok(SAMPLE_VIDEO)
        assert stats.post_id == SAMPLE_VIDEO["id"]
        assert stats.views == 10000
        assert stats.likes == 800
        assert stats.comments == 150
        assert stats.shares == 50
        assert stats.saves is None
        assert stats.impressions is None
        assert stats.reach is None
        assert stats.clicks is None

    def test_engagement_rate(self):
        stats = post_stats_from_tiktok(SAMPLE_VIDEO)
        assert stats.engagement_rate == pytest.approx((800 + 150 + 50) / 10000)

    def test_engagement_rate_none_without_views(self):
        stats = post_stats_from_tiktok({**SAMPLE_VIDEO, "view_count": 0})
        assert stats.engagement_rate is None
        stats = post_stats_from_tiktok({k: v for k, v in SAMPLE_VIDEO.items() if k != "view_count"})
        assert stats.engagement_rate is None

    def test_hashtag_extraction(self):
        post = post_from_tiktok(SAMPLE_VIDEO)
        # lowercased, de-duplicated ("#python" appears in both title and description)
        assert post.hashtags == ["python", "cleanarchitecture"]

    def test_hashtags_empty_when_no_tags(self):
        post = post_from_tiktok({**SAMPLE_VIDEO, "title": "no tags", "video_description": "plain text"})
        assert post.hashtags == []

    def test_account_stats_mapping(self):
        stats = account_stats_from_tiktok(SAMPLE_USER)
        assert stats.account_id == "open-id-abc123"
        assert stats.followers_count == 1200
        assert stats.following_count == 35
        assert stats.posts_count == 42
        assert stats.total_likes == 56000
        assert stats.total_views is None


class TestTikTokAdapter:
    """TikTok-specific adapter tests."""

    def test_cursor_pagination_round_trip(self, adapter, fake_http):
        result = adapter.list_posts(limit=2)
        assert result.has_more is True
        assert result.cursor == "1719813600"
        assert len(result.items) == 2

        adapter.list_posts(limit=2, cursor=result.cursor)
        call = fake_http.last_call()
        assert call.method == "POST"
        assert call.kwargs["json"] == {"max_count": 2, "cursor": 1719813600}

    def test_first_page_sends_no_cursor(self, adapter, fake_http):
        adapter.list_posts(limit=5)
        call = fake_http.last_call()
        assert call.kwargs["json"] == {"max_count": 5}

    def test_last_page_has_no_cursor(self, sample_post_id):
        fake = FakeHttpClient()
        fake.add("POST", "video/list/", {
            "data": {"videos": [SAMPLE_VIDEO], "cursor": 0, "has_more": False},
            "error": OK_ERROR,
        })
        adapter = TikTokSocialAdapter(credentials={"token": "test-token"}, http_client=fake)
        result = adapter.list_posts()
        assert result.has_more is False
        assert result.cursor is None
        assert result.items[0].id == sample_post_id

    def test_get_post_queries_by_id(self, adapter, fake_http, sample_post_id):
        adapter.get_post(sample_post_id)
        call = fake_http.last_call()
        assert call.kwargs["json"] == {"filters": {"video_ids": [sample_post_id]}}

    def test_get_post_not_found(self):
        fake = FakeHttpClient()
        fake.add("POST", "video/query/", {"data": {"videos": []}, "error": OK_ERROR})
        adapter = TikTokSocialAdapter(credentials={"token": "test-token"}, http_client=fake)
        with pytest.raises(PermanentProviderError):
            adapter.get_post("does-not-exist")

    def test_account_stats_period_passthrough(self, adapter):
        since = datetime(2026, 6, 1, tzinfo=UTC)
        until = datetime(2026, 7, 1, tzinfo=UTC)
        stats = adapter.get_account_stats(since=since, until=until)
        assert stats.period_start == since
        assert stats.period_end == until
        assert stats.followers_count == 1200

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert "CB Soft" in result.message

    def test_test_connection_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", "user/info/", {
            "data": {},
            "error": {"code": "access_token_invalid", "message": "The access token is invalid."},
        })
        adapter = TikTokSocialAdapter(credentials={"token": "bad-token"}, http_client=fake)
        result = adapter.test_connection()
        assert result.success is False
        assert "invalid" in result.message


PUBLISH_INIT_RESPONSE = {"data": {"publish_id": "v_pub_url~v2.123456789"}, "error": OK_ERROR}


def _status_response(status: str, **extra) -> dict:
    return {"data": {"status": status, **extra}, "error": OK_ERROR}


class TestTikTokPublish:
    """Content Posting API publish tests."""

    @pytest.fixture
    def draft(self) -> SocialPostDraft:
        return SocialPostDraft(
            title="My video #python",
            description="fallback description",
            media_type=SocialMediaType.SHORT_VIDEO,
            media_url="https://cdn.example.com/video.mp4",
            privacy=SocialPrivacy.PUBLIC,
            extra={"disable_comment": True},
        )

    def test_supports_publish_capability(self, adapter):
        assert adapter.supports(SocialPublishCapability) is True

    def test_publish_post_sends_post_info_and_source_info(self, adapter, fake_http, draft):
        fake_http.add("POST", "post/publish/video/init/", PUBLISH_INIT_RESPONSE)
        result = adapter.publish_post(draft)

        call = fake_http.last_call()
        assert call.method == "POST"
        assert call.path == "post/publish/video/init/"
        assert call.kwargs["json"] == {
            "post_info": {
                "title": "My video #python",
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_comment": True,
                "disable_duet": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": "https://cdn.example.com/video.mp4",
            },
        }
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == "v_pub_url~v2.123456789"

    def test_publish_post_private_maps_to_self_only(self, adapter, fake_http, draft):
        fake_http.add("POST", "post/publish/video/init/", PUBLISH_INIT_RESPONSE)
        adapter.publish_post(draft.model_copy(update={"privacy": SocialPrivacy.PRIVATE}))
        call = fake_http.last_call()
        assert call.kwargs["json"]["post_info"]["privacy_level"] == "SELF_ONLY"

    def test_publish_post_requires_media_url(self, adapter, draft):
        with pytest.raises(ValidationError, match="PULL_FROM_URL"):
            adapter.publish_post(draft.model_copy(update={"media_url": "", "file_path": "/tmp/video.mp4"}))
        with pytest.raises(ValidationError, match="PULL_FROM_URL"):
            adapter.publish_post(draft.model_copy(update={"media_url": "", "content": b"video-bytes"}))

    def test_publish_post_rejects_non_video(self, adapter, draft):
        with pytest.raises(ValidationError, match="only supports videos"):
            adapter.publish_post(draft.model_copy(update={"media_type": SocialMediaType.IMAGE}))

    def test_check_publish_status_complete(self, adapter, fake_http):
        fake_http.add("POST", "post/publish/status/fetch/", _status_response(
            "PUBLISH_COMPLETE", publicaly_available_post_id=[7345678901234567890],
        ))
        result = adapter.check_publish_status("v_pub_url~v2.123456789")
        call = fake_http.last_call()
        assert call.kwargs["json"] == {"publish_id": "v_pub_url~v2.123456789"}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == "7345678901234567890"
        assert result.publish_id == "v_pub_url~v2.123456789"
        assert result.extra["tiktok_status"] == "PUBLISH_COMPLETE"

    def test_check_publish_status_failed(self, adapter, fake_http):
        fake_http.add("POST", "post/publish/status/fetch/", _status_response(
            "FAILED", fail_reason="video_pull_failed",
        ))
        result = adapter.check_publish_status("v_pub_url~v2.123456789")
        assert result.status == PublishStatus.FAILED
        assert result.error == "video_pull_failed"
        assert result.extra["tiktok_status"] == "FAILED"

    def test_check_publish_status_processing(self, adapter, fake_http):
        fake_http.add("POST", "post/publish/status/fetch/", _status_response("PROCESSING_DOWNLOAD"))
        result = adapter.check_publish_status("v_pub_url~v2.123456789")
        assert result.status == PublishStatus.PROCESSING
        assert result.post_id == ""
        assert result.extra["tiktok_status"] == "PROCESSING_DOWNLOAD"


class TestTikTokPublishMappers:
    """Publish mapper tests."""

    def test_title_falls_back_to_description_and_truncates(self):
        draft = SocialPostDraft(title="", description="x" * 3000)
        info = draft_to_post_info(draft)
        assert info["title"] == "x" * 2200

    def test_unlisted_maps_to_self_only(self):
        draft = SocialPostDraft(title="t", privacy=SocialPrivacy.UNLISTED)
        assert draft_to_post_info(draft)["privacy_level"] == "SELF_ONLY"

    def test_extra_flags_default_false(self):
        info = draft_to_post_info(SocialPostDraft(title="t"))
        assert info["disable_comment"] is False
        assert info["disable_duet"] is False
        assert info["disable_stitch"] is False

    def test_publish_result_corrected_spelling_fallback(self):
        result = publish_result_from_status("pub-1", {
            "status": "PUBLISH_COMPLETE",
            "publicly_available_post_id": [42],
        })
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == "42"

    def test_publish_result_complete_without_post_id_list(self):
        result = publish_result_from_status("pub-1", {"status": "PUBLISH_COMPLETE"})
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == ""

    def test_publish_result_inbox_status_is_processing(self):
        result = publish_result_from_status("pub-1", {"status": "SEND_TO_USER_INBOX"})
        assert result.status == PublishStatus.PROCESSING
        assert result.extra["tiktok_status"] == "SEND_TO_USER_INBOX"


class TestCheckResponse:
    """Error envelope mapping tests."""

    def test_ok_returns_data(self):
        assert check_response({"data": {"user": {}}, "error": OK_ERROR}) == {"user": {}}

    def test_missing_error_returns_data(self):
        assert check_response({"data": {"videos": []}}) == {"videos": []}

    @pytest.mark.parametrize("code", ["access_token_invalid", "access_token_expired", "scope_not_authorized"])
    def test_auth_codes_raise_authentication_error(self, code):
        with pytest.raises(AuthenticationError):
            check_response({"data": {}, "error": {"code": code, "message": "denied"}})

    def test_rate_limit_raises_rate_limit_error(self):
        with pytest.raises(RateLimitError):
            check_response({"data": {}, "error": {"code": "rate_limit_exceeded", "message": "slow down"}})

    @pytest.mark.parametrize("code", ["invalid_params", "invalid_file_upload"])
    def test_validation_codes_raise_validation_error(self, code):
        with pytest.raises(ValidationError):
            check_response({"data": {}, "error": {"code": code, "message": "bad request"}})

    def test_unknown_code_raises_provider_error(self):
        with pytest.raises(ProviderError, match="something broke"):
            check_response({"data": {}, "error": {"code": "internal_error", "message": "something broke"}})
