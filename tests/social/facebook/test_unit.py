"""
Facebook Page social provider unit tests — no network, canned Graph responses.

Runs the SocialPort contract suite against a FakeHttpClient plus
provider-specific tests: insights parsing, stats merging, pagination,
media type mapping, and Graph error classification.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto.social import SocialMediaType
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
