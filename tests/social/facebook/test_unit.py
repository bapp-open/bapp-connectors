"""
Facebook Page social provider unit tests — no network, canned Graph responses.

Runs the SocialPort contract suite against a FakeHttpClient plus
provider-specific tests: insights parsing, stats merging, pagination,
media type mapping, and Graph error classification.
"""

from __future__ import annotations

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
    ProviderError,
    RateLimitError,
    ValidationError,
)
from bapp_connectors.providers.social.facebook.adapter import FacebookSocialAdapter
from bapp_connectors.providers.social.facebook.errors import check_payload, classify_graph_error
from bapp_connectors.providers.social.facebook.mappers import (
    account_from_page,
    account_stats_from_page,
    insights_to_dict,
    insights_to_totals,
    post_from_graph,
    post_stats_from_graph,
    publish_result_from_graph,
)
from tests.fake_http import FakeHttpClient
from tests.social.contract import SocialContractTests

PAGE_ID = "1234"
POST_ID = "1234_5678"

# ── Canned Graph API responses ──

PAGE_OBJECT = {
    "id": PAGE_ID,
    "name": "Test Page",
    "username": "testpage",
    "link": "https://www.facebook.com/testpage",
    "about": "A page for testing.",
    "followers_count": 1500,
    "fan_count": 1400,
    "picture": {"data": {"url": "https://cdn.example.com/avatar.jpg"}},
    "verification_status": "blue_verified",
}

POST_OBJECT = {
    "id": POST_ID,
    "message": "Big #summer #sale is live!",
    "created_time": "2026-06-01T10:00:00+0000",
    "permalink_url": "https://www.facebook.com/1234/posts/5678",
    "full_picture": "https://cdn.example.com/full.jpg",
    "attachments": {"data": [{"media_type": "photo"}]},
    "shares": {"count": 3},
    "likes": {"summary": {"total_count": 10}},
    "comments": {"summary": {"total_count": 2}},
}

VIDEO_POST_OBJECT = {
    "id": "1234_9999",
    "message": "Watch our new reel",
    "created_time": "2026-06-02T12:30:00+0000",
    "permalink_url": "https://www.facebook.com/1234/posts/9999",
    "attachments": {"data": [{"media_type": "video"}]},
    "likes": {"summary": {"total_count": 4}},
    "comments": {"summary": {"total_count": 1}},
}

POSTS_EDGE = {
    "data": [POST_OBJECT, VIDEO_POST_OBJECT],
    "paging": {
        "cursors": {"before": "BEFORE_CURSOR", "after": "AFTER_CURSOR"},
        "next": "https://graph.facebook.com/v19.0/1234/posts?after=AFTER_CURSOR",
    },
}

POST_INSIGHTS = {
    "data": [
        {"name": "post_impressions", "period": "lifetime", "values": [{"value": 100}]},
        {"name": "post_impressions_unique", "period": "lifetime", "values": [{"value": 80}]},
        {"name": "post_clicks", "period": "lifetime", "values": [{"value": 5}]},
    ],
}

PAGE_INSIGHTS = {
    "data": [
        {"name": "page_impressions", "period": "day", "values": [{"value": 10}, {"value": 20}]},
        {"name": "page_impressions_unique", "period": "day", "values": [{"value": 8}, {"value": 15}]},
    ],
}


def make_fake_http() -> FakeHttpClient:
    """FakeHttpClient with canned Graph responses (most specific paths first)."""
    fake = FakeHttpClient()
    fake.add("GET", f"{POST_ID}/insights", POST_INSIGHTS)
    fake.add("GET", POST_ID, POST_OBJECT)
    fake.add("GET", f"{PAGE_ID}/posts", POSTS_EDGE)
    fake.add("GET", f"{PAGE_ID}/insights", PAGE_INSIGHTS)
    fake.add("GET", PAGE_ID, PAGE_OBJECT)
    return fake


def make_adapter(fake: FakeHttpClient | None = None) -> FacebookSocialAdapter:
    return FacebookSocialAdapter(
        credentials={"token": "test_page_token", "page_id": PAGE_ID},
        http_client=fake or make_fake_http(),
    )


# ── Contract ──


class TestFacebookContract(SocialContractTests):

    @pytest.fixture
    def adapter(self) -> FacebookSocialAdapter:
        return make_adapter()

    @pytest.fixture
    def sample_post_id(self) -> str:
        return POST_ID


# ── Insights parsing ──


class TestInsightsParsing:

    def test_insights_to_dict_takes_latest_value(self):
        payload = {
            "data": [
                {"name": "post_impressions", "values": [{"value": 50}, {"value": 100}]},
                {"name": "post_clicks", "values": [{"value": 5}]},
            ],
        }
        result = insights_to_dict(payload)
        assert result == {"post_impressions": 100, "post_clicks": 5}

    def test_insights_to_dict_empty_payload(self):
        assert insights_to_dict({}) == {}
        assert insights_to_dict({"data": [{"name": "post_impressions", "values": []}]}) == {}

    def test_insights_to_totals_sums_daily_values(self):
        result = insights_to_totals(PAGE_INSIGHTS)
        assert result == {"page_impressions": 30, "page_impressions_unique": 23}


# ── Stats merging ──


class TestPostStats:

    def test_engagement_only(self):
        stats = post_stats_from_graph(POST_OBJECT)
        assert stats.post_id == POST_ID
        assert stats.likes == 10
        assert stats.comments == 2
        assert stats.shares == 3
        assert stats.impressions is None
        assert stats.engagement_rate is None

    def test_merge_with_insights(self):
        insights = insights_to_dict(POST_INSIGHTS)
        stats = post_stats_from_graph(POST_OBJECT, insights)
        assert stats.likes == 10
        assert stats.impressions == 100
        assert stats.reach == 80
        assert stats.clicks == 5
        assert stats.views is None  # post_video_views absent
        assert stats.engagement_rate == pytest.approx((10 + 2 + 3) / 100)

    def test_adapter_tolerates_insights_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", f"{POST_ID}/insights", lambda m, p, k: (_ for _ in ()).throw(ProviderError("boom")))
        fake.add("GET", POST_ID, POST_OBJECT)
        stats = make_adapter(fake).get_post_stats(POST_ID)
        assert stats.post_id == POST_ID
        assert stats.likes == 10
        assert stats.impressions is None


# ── Account stats ──


class TestAccountStats:

    def test_sums_daily_impressions(self):
        stats = make_adapter().get_account_stats()
        assert stats.account_id == PAGE_ID
        assert stats.followers_count == 1500
        assert stats.impressions == 30
        assert stats.reach == 23
        assert stats.posts_count is None

    def test_without_insights(self):
        stats = account_stats_from_page(PAGE_OBJECT, None)
        assert stats.followers_count == 1500
        assert stats.impressions is None

    def test_period_passthrough_as_unix_timestamps(self):
        from datetime import UTC, datetime

        since = datetime(2026, 6, 1, tzinfo=UTC)
        until = datetime(2026, 6, 30, tzinfo=UTC)
        fake = make_fake_http()
        stats = make_adapter(fake).get_account_stats(since=since, until=until)
        assert stats.period_start == since
        assert stats.period_end == until
        insights_call = next(c for c in fake.calls if c.path.endswith("/insights"))
        assert insights_call.kwargs["params"]["since"] == int(since.timestamp())
        assert insights_call.kwargs["params"]["until"] == int(until.timestamp())


# ── Pagination ──


class TestPagination:

    def test_cursor_and_has_more(self):
        result = make_adapter().list_posts(limit=5)
        assert len(result.items) == 2
        assert result.cursor == "AFTER_CURSOR"
        assert result.has_more is True

    def test_no_next_page(self):
        fake = FakeHttpClient()
        fake.add("GET", f"{PAGE_ID}/posts", {
            "data": [POST_OBJECT],
            "paging": {"cursors": {"before": "B", "after": "A"}},
        })
        result = make_adapter(fake).list_posts()
        assert result.has_more is False

    def test_cursor_forwarded_as_after_param(self):
        fake = make_fake_http()
        make_adapter(fake).list_posts(limit=10, cursor="MY_CURSOR")
        call = fake.last_call()
        assert call.kwargs["params"]["after"] == "MY_CURSOR"
        assert call.kwargs["params"]["limit"] == 10


# ── Media type mapping ──


class TestMediaType:

    def test_video_attachment(self):
        assert post_from_graph(VIDEO_POST_OBJECT).media_type == SocialMediaType.VIDEO

    def test_photo_attachment(self):
        assert post_from_graph(POST_OBJECT).media_type == SocialMediaType.IMAGE

    def test_album_attachment(self):
        post = {**POST_OBJECT, "attachments": {"data": [{"media_type": "album"}]}}
        assert post_from_graph(post).media_type == SocialMediaType.CAROUSEL

    def test_no_attachment_is_text(self):
        post = {k: v for k, v in POST_OBJECT.items() if k != "attachments"}
        assert post_from_graph(post).media_type == SocialMediaType.TEXT

    def test_unknown_attachment_is_other(self):
        post = {**POST_OBJECT, "attachments": {"data": [{"media_type": "event"}]}}
        assert post_from_graph(post).media_type == SocialMediaType.OTHER


# ── Post mapping ──


class TestPostMapping:

    def test_fields(self):
        post = post_from_graph(POST_OBJECT)
        assert post.id == POST_ID
        assert post.account_id == PAGE_ID
        assert post.url == "https://www.facebook.com/1234/posts/5678"
        assert post.description == "Big #summer #sale is live!"
        assert post.thumbnail_url == "https://cdn.example.com/full.jpg"
        assert post.hashtags == ["summer", "sale"]
        assert post.published_at is not None
        assert post.published_at.year == 2026
        assert post.stats is not None
        assert post.stats.likes == 10

    def test_account_mapping(self):
        account = account_from_page(PAGE_OBJECT)
        assert account.id == PAGE_ID
        assert account.display_name == "Test Page"
        assert account.avatar_url == "https://cdn.example.com/avatar.jpg"
        assert account.followers_count == 1500
        assert account.is_verified is True

    def test_account_verification_absent_is_none(self):
        page = {k: v for k, v in PAGE_OBJECT.items() if k != "verification_status"}
        assert account_from_page(page).is_verified is None

    def test_account_followers_fallback_to_fan_count(self):
        page = {k: v for k, v in PAGE_OBJECT.items() if k != "followers_count"}
        assert account_from_page(page).followers_count == 1400


# ── Graph error classification ──


class TestGraphErrors:

    def test_code_190_is_authentication_error(self):
        error = classify_graph_error({"error": {"code": 190, "message": "Invalid OAuth access token."}})
        assert isinstance(error, AuthenticationError)

    @pytest.mark.parametrize("code", [4, 17, 32, 613])
    def test_throttling_codes_are_rate_limit_errors(self, code):
        error = classify_graph_error({"error": {"code": code, "message": "Too many calls."}})
        assert isinstance(error, RateLimitError)

    def test_code_100_is_validation_error(self):
        error = classify_graph_error({"error": {"code": 100, "message": "Unsupported field."}})
        assert isinstance(error, ValidationError)

    def test_unknown_code_is_provider_error(self):
        error = classify_graph_error({"error": {"code": 1, "message": "Unknown error."}})
        assert isinstance(error, ProviderError)
        assert "Unknown error." in str(error)

    def test_check_payload_raises_on_error_body(self):
        with pytest.raises(AuthenticationError):
            check_payload({"error": {"code": 190, "message": "expired"}})

    def test_check_payload_passes_clean_body(self):
        payload = {"id": PAGE_ID, "name": "Test Page"}
        assert check_payload(payload) is payload

    def test_client_raises_on_error_in_200_body(self):
        fake = FakeHttpClient()
        fake.add("GET", PAGE_ID, {"error": {"code": 190, "message": "expired token"}})
        with pytest.raises(AuthenticationError):
            make_adapter(fake).get_account()


# ── Publishing ──


class TestPublishPost:

    def test_text_post_hits_feed_edge(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/feed", {"id": f"{PAGE_ID}_111"})
        draft = SocialPostDraft(
            media_type=SocialMediaType.TEXT,
            description="Hello world",
            link="https://example.com/offer",
        )
        result = make_adapter(fake).publish_post(draft)

        call = fake.last_call()
        assert call.method == "POST"
        assert call.path == f"{PAGE_ID}/feed"
        assert call.kwargs["json"] == {"message": "Hello world", "link": "https://example.com/offer"}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == f"{PAGE_ID}_111"
        assert result.url == f"https://www.facebook.com/{PAGE_ID}_111"

    def test_text_post_without_message_or_link_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT)
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_photo_via_url(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/photos", {"id": "777", "post_id": f"{PAGE_ID}_777"})
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            media_url="https://cdn.example.com/pic.jpg",
            description="Nice pic",
        )
        result = make_adapter(fake).publish_post(draft)

        call = fake.last_call()
        assert call.path == f"{PAGE_ID}/photos"
        assert call.kwargs["json"] == {"url": "https://cdn.example.com/pic.jpg", "caption": "Nice pic"}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == f"{PAGE_ID}_777"
        assert result.url == f"https://www.facebook.com/{PAGE_ID}_777"

    def test_photo_via_content_bytes_is_multipart(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/photos", {"id": "778", "post_id": f"{PAGE_ID}_778"})
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            content=b"jpegbytes",
            filename="pic.jpg",
            description="Uploaded pic",
        )
        result = make_adapter(fake).publish_post(draft)

        call = fake.last_call()
        assert call.path == f"{PAGE_ID}/photos"
        assert call.kwargs["files"] == {"source": ("pic.jpg", b"jpegbytes")}
        assert call.kwargs["data"] == {"caption": "Uploaded pic"}
        assert result.post_id == f"{PAGE_ID}_778"

    def test_video_via_url_returns_processing(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/videos", {"id": "555"})
        draft = SocialPostDraft(
            media_type=SocialMediaType.VIDEO,
            media_url="https://cdn.example.com/clip.mp4",
            title="Clip",
            description="A clip",
        )
        result = make_adapter(fake).publish_post(draft)

        call = fake.last_call()
        assert call.path == f"{PAGE_ID}/videos"
        assert call.kwargs["json"] == {
            "file_url": "https://cdn.example.com/clip.mp4",
            "description": "A clip",
            "title": "Clip",
        }
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == "555"
        assert result.post_id == ""

    def test_extra_is_merged_into_payload_last(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/feed", {"id": f"{PAGE_ID}_112"})
        draft = SocialPostDraft(
            media_type=SocialMediaType.TEXT,
            description="Scheduled",
            extra={"published": False, "scheduled_publish_time": 1780000000},
        )
        make_adapter(fake).publish_post(draft)

        payload = fake.last_call().kwargs["json"]
        assert payload["published"] is False
        assert payload["scheduled_publish_time"] == 1780000000

    def test_non_public_privacy_raises(self):
        draft = SocialPostDraft(
            media_type=SocialMediaType.TEXT,
            description="Secret",
            privacy=SocialPrivacy.PRIVATE,
        )
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)


class TestPublishResultMapping:

    def test_photo_response_prefers_post_id(self):
        result = publish_result_from_graph({"id": "777", "post_id": "1234_777"}, PAGE_ID, is_video=False)
        assert result.post_id == "1234_777"
        assert result.status == PublishStatus.PUBLISHED

    def test_video_response_is_processing(self):
        result = publish_result_from_graph({"id": "555"}, PAGE_ID, is_video=True)
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == "555"
        assert result.post_id == ""


class TestCheckPublishStatus:

    VIDEO_ID = "555"

    def _status(self, payload: dict):
        fake = FakeHttpClient()
        fake.add("GET", self.VIDEO_ID, payload)
        return make_adapter(fake).check_publish_status(self.VIDEO_ID)

    def test_ready_is_published_with_absolute_url(self):
        result = self._status({
            "id": self.VIDEO_ID,
            "status": {"video_status": "ready"},
            "permalink_url": f"/{PAGE_ID}/videos/{self.VIDEO_ID}",
        })
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == self.VIDEO_ID
        assert result.url == f"https://www.facebook.com/{PAGE_ID}/videos/{self.VIDEO_ID}"

    def test_processing_stays_processing(self):
        result = self._status({"id": self.VIDEO_ID, "status": {"video_status": "processing"}})
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == self.VIDEO_ID

    def test_error_is_failed(self):
        result = self._status({"id": self.VIDEO_ID, "status": {"video_status": "error"}})
        assert result.status == PublishStatus.FAILED
        assert result.error != ""

    def test_object_without_status_is_published(self):
        fake = FakeHttpClient()
        fake.add("GET", POST_ID, {"id": POST_ID, "permalink_url": "https://www.facebook.com/1234/posts/5678"})
        result = make_adapter(fake).check_publish_status(POST_ID)
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == POST_ID
        assert result.url == "https://www.facebook.com/1234/posts/5678"


class TestPublishCapability:

    def test_adapter_supports_social_publish(self):
        assert make_adapter().supports(SocialPublishCapability) is True


# ── Connection test ──


class TestConnection:

    def test_success_message_includes_page_name(self):
        result = make_adapter().test_connection()
        assert result.success is True
        assert "Test Page" in result.message

    def test_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", PAGE_ID, {"error": {"code": 190, "message": "expired token"}})
        result = make_adapter(fake).test_connection()
        assert result.success is False
