"""
Instagram social provider unit tests — no network, canned Graph responses.

Runs the SocialPort contract suite against a FakeHttpClient plus
provider-specific tests: insights parsing, stats merging, pagination,
media type mapping (incl. Reels), two-step publishing, container status
polling, OAuth, and Graph error classification.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
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
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.instagram.adapter import InstagramSocialAdapter
from bapp_connectors.providers.social.instagram.errors import check_payload, classify_graph_error
from bapp_connectors.providers.social.instagram.manifest import manifest
from bapp_connectors.providers.social.instagram.mappers import (
    account_from_ig,
    account_stats_from_ig,
    insights_to_dict,
    insights_to_totals,
    post_from_ig,
    post_stats_from_ig,
)
from tests.fake_http import FakeHttpClient
from tests.social.contract import SocialContractTests

IG_USER_ID = "17841400000000000"
MEDIA_ID = "17900000000000001"
REELS_MEDIA_ID = "17900000000000002"
CREATION_ID = "18000000000000001"

# ── Canned Graph API responses ──

USER_OBJECT = {
    "id": IG_USER_ID,
    "username": "teststore",
    "name": "Test Store",
    "biography": "We sell test things.",
    "profile_picture_url": "https://cdn.example.com/avatar.jpg",
    "website": "https://example.com",
    "followers_count": 2500,
    "follows_count": 120,
    "media_count": 42,
}

IMAGE_MEDIA = {
    "id": MEDIA_ID,
    "caption": "Big #summer #sale is live!",
    "media_type": "IMAGE",
    "media_product_type": "FEED",
    "media_url": "https://cdn.example.com/pic.jpg",
    "permalink": "https://www.instagram.com/p/ABC123/",
    "timestamp": "2026-06-01T10:00:00+0000",
    "like_count": 10,
    "comments_count": 2,
}

REELS_MEDIA = {
    "id": REELS_MEDIA_ID,
    "caption": "Watch our new reel",
    "media_type": "VIDEO",
    "media_product_type": "REELS",
    "media_url": "https://cdn.example.com/reel.mp4",
    "permalink": "https://www.instagram.com/reel/DEF456/",
    "thumbnail_url": "https://cdn.example.com/reel-thumb.jpg",
    "timestamp": "2026-06-02T12:30:00+0000",
    "like_count": 4,
    "comments_count": 1,
}

MEDIA_EDGE = {
    "data": [IMAGE_MEDIA, REELS_MEDIA],
    "paging": {
        "cursors": {"before": "BEFORE_CURSOR", "after": "AFTER_CURSOR"},
        "next": f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media?after=AFTER_CURSOR",
    },
}

MEDIA_INSIGHTS = {
    "data": [
        {"name": "impressions", "period": "lifetime", "values": [{"value": 100}]},
        {"name": "reach", "period": "lifetime", "values": [{"value": 80}]},
        {"name": "saved", "period": "lifetime", "values": [{"value": 7}]},
    ],
}

VIDEO_INSIGHTS = {
    "data": [
        {"name": "plays", "period": "lifetime", "values": [{"value": 60}]},
    ],
}

ACCOUNT_INSIGHTS = {
    "data": [
        {"name": "impressions", "period": "day", "values": [{"value": 10}, {"value": 20}]},
        {"name": "reach", "period": "day", "values": [{"value": 8}, {"value": 15}]},
    ],
}


def make_fake_http() -> FakeHttpClient:
    """FakeHttpClient with canned Graph responses (most specific paths first)."""
    fake = FakeHttpClient()
    fake.add("GET", f"{MEDIA_ID}/insights", MEDIA_INSIGHTS)
    fake.add("GET", MEDIA_ID, IMAGE_MEDIA)
    fake.add("GET", f"{IG_USER_ID}/media", MEDIA_EDGE)
    fake.add("GET", f"{IG_USER_ID}/insights", ACCOUNT_INSIGHTS)
    fake.add("GET", IG_USER_ID, USER_OBJECT)
    return fake


def make_adapter(fake: FakeHttpClient | None = None) -> InstagramSocialAdapter:
    return InstagramSocialAdapter(
        credentials={"token": "test_page_token", "ig_user_id": IG_USER_ID},
        http_client=fake or make_fake_http(),
    )


# ── Contract ──


class TestInstagramContract(SocialContractTests):

    @pytest.fixture
    def adapter(self) -> InstagramSocialAdapter:
        return make_adapter()

    @pytest.fixture
    def sample_post_id(self) -> str:
        return MEDIA_ID


# ── Capabilities ──


class TestCapabilities:

    def test_supports_social_port(self):
        assert make_adapter().supports(SocialPort) is True

    def test_supports_social_publish(self):
        assert make_adapter().supports(SocialPublishCapability) is True

    def test_supports_oauth(self):
        assert make_adapter().supports(OAuthCapability) is True


# ── Insights parsing ──


class TestInsightsParsing:

    def test_insights_to_dict_takes_latest_value(self):
        payload = {
            "data": [
                {"name": "impressions", "values": [{"value": 50}, {"value": 100}]},
                {"name": "saved", "values": [{"value": 5}]},
            ],
        }
        result = insights_to_dict(payload)
        assert result == {"impressions": 100, "saved": 5}

    def test_insights_to_dict_empty_payload(self):
        assert insights_to_dict({}) == {}
        assert insights_to_dict({"data": [{"name": "impressions", "values": []}]}) == {}

    def test_insights_to_totals_sums_daily_values(self):
        result = insights_to_totals(ACCOUNT_INSIGHTS)
        assert result == {"impressions": 30, "reach": 23}


# ── Stats merging ──


class TestPostStats:

    def test_engagement_only(self):
        stats = post_stats_from_ig(IMAGE_MEDIA)
        assert stats.post_id == MEDIA_ID
        assert stats.likes == 10
        assert stats.comments == 2
        assert stats.impressions is None
        assert stats.saves is None
        assert stats.engagement_rate is None

    def test_merge_with_insights(self):
        insights = insights_to_dict(MEDIA_INSIGHTS)
        stats = post_stats_from_ig(IMAGE_MEDIA, insights)
        assert stats.likes == 10
        assert stats.comments == 2
        assert stats.impressions == 100
        assert stats.reach == 80
        assert stats.saves == 7
        assert stats.views is None  # no video metric for an image
        assert stats.engagement_rate == pytest.approx((10 + 2) / 100)

    def test_views_from_plays_fallback(self):
        stats = post_stats_from_ig(REELS_MEDIA, {"plays": 60})
        assert stats.views == 60

    def test_views_prefers_video_views(self):
        stats = post_stats_from_ig(REELS_MEDIA, {"video_views": 55, "plays": 60})
        assert stats.views == 55

    def test_adapter_merges_video_insights_for_videos(self):
        fake = FakeHttpClient()

        def insights_router(method, path, kwargs):
            if "plays" in kwargs["params"]["metric"]:
                return VIDEO_INSIGHTS
            return MEDIA_INSIGHTS

        fake.add("GET", f"{REELS_MEDIA_ID}/insights", insights_router)
        fake.add("GET", REELS_MEDIA_ID, REELS_MEDIA)
        stats = make_adapter(fake).get_post_stats(REELS_MEDIA_ID)
        assert stats.likes == 4
        assert stats.impressions == 100
        assert stats.saves == 7
        assert stats.views == 60

    def test_adapter_tolerates_insights_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", f"{MEDIA_ID}/insights", lambda m, p, k: (_ for _ in ()).throw(ProviderError("boom")))
        fake.add("GET", MEDIA_ID, IMAGE_MEDIA)
        stats = make_adapter(fake).get_post_stats(MEDIA_ID)
        assert stats.post_id == MEDIA_ID
        assert stats.likes == 10
        assert stats.impressions is None

    def test_adapter_tolerates_video_insights_failure(self):
        fake = FakeHttpClient()

        def insights_router(method, path, kwargs):
            if "plays" in kwargs["params"]["metric"]:
                raise ValidationError("(#100) metric not supported")
            return MEDIA_INSIGHTS

        fake.add("GET", f"{REELS_MEDIA_ID}/insights", insights_router)
        fake.add("GET", REELS_MEDIA_ID, REELS_MEDIA)
        stats = make_adapter(fake).get_post_stats(REELS_MEDIA_ID)
        assert stats.impressions == 100
        assert stats.views is None


# ── Account stats ──


class TestAccountStats:

    def test_sums_daily_impressions(self):
        stats = make_adapter().get_account_stats()
        assert stats.account_id == IG_USER_ID
        assert stats.followers_count == 2500
        assert stats.posts_count == 42
        assert stats.impressions == 30
        assert stats.reach == 23

    def test_without_insights(self):
        stats = account_stats_from_ig(USER_OBJECT, None)
        assert stats.followers_count == 2500
        assert stats.posts_count == 42
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
        assert insights_call.kwargs["params"]["period"] == "day"


# ── Pagination ──


class TestPagination:

    def test_cursor_and_has_more(self):
        result = make_adapter().list_posts(limit=5)
        assert len(result.items) == 2
        assert result.cursor == "AFTER_CURSOR"
        assert result.has_more is True

    def test_no_next_page(self):
        fake = FakeHttpClient()
        fake.add("GET", f"{IG_USER_ID}/media", {
            "data": [IMAGE_MEDIA],
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

    def test_image(self):
        assert post_from_ig(IMAGE_MEDIA).media_type == SocialMediaType.IMAGE

    def test_reels_is_short_video(self):
        assert post_from_ig(REELS_MEDIA).media_type == SocialMediaType.SHORT_VIDEO

    def test_feed_video_is_video(self):
        media = {**REELS_MEDIA, "media_product_type": "FEED"}
        assert post_from_ig(media).media_type == SocialMediaType.VIDEO

    def test_carousel_album_is_carousel(self):
        media = {**IMAGE_MEDIA, "media_type": "CAROUSEL_ALBUM"}
        assert post_from_ig(media).media_type == SocialMediaType.CAROUSEL

    def test_unknown_is_other(self):
        media = {**IMAGE_MEDIA, "media_type": "STORY_THING"}
        assert post_from_ig(media).media_type == SocialMediaType.OTHER


# ── Post / account mapping ──


class TestPostMapping:

    def test_fields(self):
        post = post_from_ig(IMAGE_MEDIA)
        assert post.id == MEDIA_ID
        assert post.url == "https://www.instagram.com/p/ABC123/"
        assert post.description == "Big #summer #sale is live!"
        assert post.media_url == "https://cdn.example.com/pic.jpg"
        assert post.hashtags == ["summer", "sale"]
        assert post.published_at is not None
        assert post.published_at.year == 2026
        assert post.stats is not None
        assert post.stats.likes == 10
        assert post.stats.comments == 2

    def test_reels_thumbnail(self):
        post = post_from_ig(REELS_MEDIA)
        assert post.thumbnail_url == "https://cdn.example.com/reel-thumb.jpg"

    def test_account_mapping(self):
        account = account_from_ig(USER_OBJECT)
        assert account.id == IG_USER_ID
        assert account.username == "teststore"
        assert account.display_name == "Test Store"
        assert account.profile_url == "https://www.instagram.com/teststore/"
        assert account.avatar_url == "https://cdn.example.com/avatar.jpg"
        assert account.description == "We sell test things."
        assert account.followers_count == 2500
        assert account.following_count == 120
        assert account.posts_count == 42
        assert account.extra == {"website": "https://example.com"}

    def test_account_without_username_has_no_profile_url(self):
        user = {k: v for k, v in USER_OBJECT.items() if k != "username"}
        assert account_from_ig(user).profile_url == ""


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
        payload = {"id": IG_USER_ID, "username": "teststore"}
        assert check_payload(payload) is payload

    def test_client_raises_on_error_in_200_body(self):
        fake = FakeHttpClient()
        fake.add("GET", IG_USER_ID, {"error": {"code": 190, "message": "expired token"}})
        with pytest.raises(AuthenticationError):
            make_adapter(fake).get_account()


# ── Publishing ──


class TestPublishPost:

    def test_image_is_two_step_container_then_publish(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{IG_USER_ID}/media_publish", {"id": MEDIA_ID})
        fake.add("POST", f"{IG_USER_ID}/media", {"id": CREATION_ID})
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            media_url="https://cdn.example.com/pic.jpg",
            description="Nice pic",
        )
        result = make_adapter(fake).publish_post(draft)

        container_call, publish_call = fake.calls
        assert container_call.method == "POST"
        assert container_call.path == f"{IG_USER_ID}/media"
        assert container_call.kwargs["json"] == {"image_url": "https://cdn.example.com/pic.jpg", "caption": "Nice pic"}
        assert publish_call.method == "POST"
        assert publish_call.path == f"{IG_USER_ID}/media_publish"
        assert publish_call.kwargs["json"] == {"creation_id": CREATION_ID}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == MEDIA_ID
        assert result.publish_id == CREATION_ID

    def test_video_returns_processing_with_creation_id(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{IG_USER_ID}/media", {"id": CREATION_ID})
        draft = SocialPostDraft(
            media_type=SocialMediaType.VIDEO,
            media_url="https://cdn.example.com/clip.mp4",
            description="A clip",
        )
        result = make_adapter(fake).publish_post(draft)

        call = fake.last_call()
        assert call.path == f"{IG_USER_ID}/media"
        assert call.kwargs["json"] == {
            "media_type": "REELS",
            "video_url": "https://cdn.example.com/clip.mp4",
            "caption": "A clip",
        }
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == CREATION_ID
        assert result.post_id == ""

    def test_short_video_is_published_as_reels(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{IG_USER_ID}/media", {"id": CREATION_ID})
        draft = SocialPostDraft(
            media_type=SocialMediaType.SHORT_VIDEO,
            media_url="https://cdn.example.com/reel.mp4",
        )
        result = make_adapter(fake).publish_post(draft)
        assert fake.last_call().kwargs["json"]["media_type"] == "REELS"
        assert result.status == PublishStatus.PROCESSING

    def test_extra_is_merged_into_payload_last(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{IG_USER_ID}/media_publish", {"id": MEDIA_ID})
        fake.add("POST", f"{IG_USER_ID}/media", {"id": CREATION_ID})
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            media_url="https://cdn.example.com/pic.jpg",
            extra={"user_tags": '[{"username":"friend"}]'},
        )
        make_adapter(fake).publish_post(draft)
        assert fake.calls[0].kwargs["json"]["user_tags"] == '[{"username":"friend"}]'

    def test_file_path_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.IMAGE, file_path="/tmp/pic.jpg")
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_content_bytes_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.IMAGE, content=b"jpegbytes", filename="pic.jpg")
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_text_only_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT, description="Hello world")
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_non_public_privacy_raises(self):
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            media_url="https://cdn.example.com/pic.jpg",
            privacy=SocialPrivacy.PRIVATE,
        )
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)


class TestCheckPublishStatus:

    def _status(self, payload: dict, fake: FakeHttpClient | None = None):
        fake = fake or FakeHttpClient()
        fake.add("GET", CREATION_ID, payload)
        return make_adapter(fake).check_publish_status(CREATION_ID)

    def test_finished_publishes_and_returns_published(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{IG_USER_ID}/media_publish", {"id": MEDIA_ID})
        result = self._status({"id": CREATION_ID, "status_code": "FINISHED"}, fake)

        publish_call = fake.last_call()
        assert publish_call.method == "POST"
        assert publish_call.path == f"{IG_USER_ID}/media_publish"
        assert publish_call.kwargs["json"] == {"creation_id": CREATION_ID}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == MEDIA_ID
        assert result.publish_id == CREATION_ID

    def test_in_progress_stays_processing(self):
        result = self._status({"id": CREATION_ID, "status_code": "IN_PROGRESS"})
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == CREATION_ID

    def test_error_is_failed(self):
        result = self._status({"id": CREATION_ID, "status_code": "ERROR", "status": "Media upload failed."})
        assert result.status == PublishStatus.FAILED
        assert result.error == "Media upload failed."

    def test_expired_is_failed(self):
        result = self._status({"id": CREATION_ID, "status_code": "EXPIRED"})
        assert result.status == PublishStatus.FAILED
        assert result.error != ""

    def test_already_published_container(self):
        result = self._status({"id": CREATION_ID, "status_code": "PUBLISHED"})
        assert result.status == PublishStatus.PUBLISHED
        assert result.publish_id == CREATION_ID


# ── OAuth ──


OAUTH_SCOPES = ["instagram_basic", "instagram_content_publish", "instagram_manage_insights", "pages_show_list"]


class TestInstagramOAuth:

    def make_oauth_adapter(self, fake: FakeHttpClient | None = None) -> InstagramSocialAdapter:
        return InstagramSocialAdapter(
            credentials={"app_id": "app_123", "app_secret": "app_secret_456", "ig_user_id": IG_USER_ID},
            http_client=fake or FakeHttpClient(),
        )

    def test_oauth_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Instagram"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["app_id", "app_secret"]
        assert manifest.auth.oauth.scopes == OAUTH_SCOPES

    def test_token_not_required_in_manifest(self):
        token_field = next(f for f in manifest.auth.required_fields if f.name == "token")
        assert token_field.required is False
        ig_user_id_field = next(f for f in manifest.auth.required_fields if f.name == "ig_user_id")
        assert ig_user_id_field.required is True

    def test_adapter_constructible_with_app_credentials_only(self):
        adapter = InstagramSocialAdapter(credentials={"app_id": "app_123", "app_secret": "app_secret_456"})
        assert adapter._app_id == "app_123"
        assert adapter._app_secret == "app_secret_456"
        assert adapter.validate_credentials() is True

    def test_validate_credentials_without_app_credentials(self):
        assert make_adapter().validate_credentials() is True  # token + ig_user_id
        no_token = InstagramSocialAdapter(credentials={"ig_user_id": IG_USER_ID}, http_client=FakeHttpClient())
        assert no_token.validate_credentials() is False

    def test_get_authorize_url(self):
        url = self.make_oauth_adapter().get_authorize_url("https://example.com/cb", state="xyz789")
        assert url.startswith("https://www.facebook.com/v19.0/dialog/oauth?")
        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == ["app_123"]
        assert query["redirect_uri"] == ["https://example.com/cb"]
        assert query["state"] == ["xyz789"]
        assert query["scope"] == [",".join(OAUTH_SCOPES)]

    def test_exchange_code_for_token(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "oauth/access_token",
            {"access_token": "USER_TOKEN", "token_type": "bearer", "expires_in": 5183944},
        )
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")

        call = fake.last_call()
        assert call.method == "GET"
        assert call.path == "oauth/access_token"
        assert call.kwargs["params"]["client_id"] == "app_123"
        assert call.kwargs["params"]["client_secret"] == "app_secret_456"
        assert call.kwargs["params"]["code"] == "the_code"
        assert call.kwargs["params"]["redirect_uri"] == "https://example.com/cb"
        assert tokens.access_token == "USER_TOKEN"
        assert tokens.refresh_token == ""  # Meta has no refresh tokens
        assert tokens.expires_in == 5183944
        assert tokens.extra["credentials"] == {
            "token": "USER_TOKEN",
            "app_id": "app_123",
            "app_secret": "app_secret_456",
        }

    def test_refresh_token_is_long_lived_exchange(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "oauth/access_token",
            {"access_token": "LONG_LIVED_TOKEN", "token_type": "bearer", "expires_in": 5184000},
        )
        tokens = self.make_oauth_adapter(fake).refresh_token("SHORT_LIVED_TOKEN")

        params = fake.last_call().kwargs["params"]
        assert params["grant_type"] == "fb_exchange_token"
        assert params["fb_exchange_token"] == "SHORT_LIVED_TOKEN"
        assert params["client_id"] == "app_123"
        assert params["client_secret"] == "app_secret_456"
        assert tokens.access_token == "LONG_LIVED_TOKEN"
        assert tokens.refresh_token == ""
        assert tokens.expires_in == 5184000

    def test_list_instagram_accounts(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "me/accounts",
            {
                "data": [
                    {
                        "id": "1234",
                        "name": "Store Page",
                        "access_token": "PAGE_TOKEN",
                        "instagram_business_account": {"id": IG_USER_ID},
                    },
                    {"id": "5678", "name": "Plain Page", "access_token": "OTHER_TOKEN"},
                ],
            },
        )
        accounts = self.make_oauth_adapter(fake).list_instagram_accounts("USER_TOKEN")

        call = fake.last_call()
        assert call.method == "GET"
        assert call.path == "me/accounts"
        assert call.kwargs["params"] == {
            "access_token": "USER_TOKEN",
            "fields": "id,name,access_token,instagram_business_account",
        }
        assert accounts == [
            {"page_id": "1234", "page_name": "Store Page", "page_token": "PAGE_TOKEN", "ig_user_id": IG_USER_ID},
        ]

    def test_list_instagram_accounts_raises_on_graph_error(self):
        fake = FakeHttpClient()
        fake.add("GET", "me/accounts", {"error": {"code": 190, "message": "expired token"}})
        with pytest.raises(AuthenticationError):
            self.make_oauth_adapter(fake).list_instagram_accounts("BAD_TOKEN")


# ── Connection test ──


class TestConnection:

    def test_success_message_includes_username(self):
        result = make_adapter().test_connection()
        assert result.success is True
        assert "teststore" in result.message

    def test_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", IG_USER_ID, {"error": {"code": 190, "message": "expired token"}})
        result = make_adapter(fake).test_connection()
        assert result.success is False
