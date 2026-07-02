"""
Pinterest social adapter unit tests + contract tests.

Runs the SocialPort contract suite against a FakeHttpClient plus
provider-specific tests: bookmark pagination, analytics mapping, the
None-fields rule, image pin publishing, and the OAuth Basic-auth flow.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.dto.social import (
    PublishStatus,
    SocialMediaType,
    SocialPostDraft,
)
from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ValidationError,
)
from bapp_connectors.providers.social.pinterest.adapter import PinterestSocialAdapter
from bapp_connectors.providers.social.pinterest.manifest import manifest
from bapp_connectors.providers.social.pinterest.mappers import (
    account_from_pinterest,
    account_stats_from_analytics,
    post_from_pin,
    stats_from_pin_analytics,
)
from tests.fake_http import FakeHttpClient
from tests.social.contract import SocialContractTests

PIN_ID = "813744226420795884"
PIN_ID_2 = "813744226420795885"

USER_ACCOUNT = {
    "username": "cbsoft",
    "id": "1234567890",
    "profile_image": "https://i.pinimg.com/avatars/cbsoft.jpg",
    "about": "Building connectors.",
    "follower_count": 320,
    "following_count": 12,
    "monthly_views": 45000,
    "pin_count": 87,
    "account_type": "BUSINESS",
}

IMAGE_PIN = {
    "id": PIN_ID,
    "created_at": "2026-06-01T10:00:00Z",
    "link": "https://example.com/product",
    "title": "Summer #sale poster",
    "description": "Our best #summer deals in one pin",
    "board_id": "board-111",
    "media": {
        "media_type": "image",
        "images": {
            "150x150": {"url": "https://i.pinimg.com/150x150/pin.jpg", "width": 150, "height": 150},
            "600x": {"url": "https://i.pinimg.com/600x/pin.jpg", "width": 600, "height": 900},
            "1200x": {"url": "https://i.pinimg.com/1200x/pin.jpg", "width": 1200, "height": 1800},
        },
    },
}

VIDEO_PIN = {
    "id": PIN_ID_2,
    "created_at": "2026-05-20T08:30:00",  # Pinterest also returns naive UTC timestamps
    "link": None,
    "title": None,
    "description": "Behind the scenes",
    "board_id": "board-111",
    "media": {"media_type": "video", "images": {}},
}

PINS_PAGE = {"items": [IMAGE_PIN, VIDEO_PIN], "bookmark": "BOOKMARK_1"}

PIN_ANALYTICS = {
    "all": {
        "lifetime_metrics": {
            "IMPRESSION": 1000,
            "PIN_CLICK": 40,
            "OUTBOUND_CLICK": 15,
            "SAVE": 25,
        },
    },
}

USER_ANALYTICS = {
    "all": {
        "lifetime_metrics": {
            "IMPRESSION": 5000,
            "PIN_CLICK": 120,
            "OUTBOUND_CLICK": 60,
            "SAVE": 80,
        },
    },
}


@pytest.fixture
def sample_post_id() -> str:
    return PIN_ID


def make_fake_http() -> FakeHttpClient:
    """FakeHttpClient with canned Pinterest v5 responses (most specific paths first)."""
    fake = FakeHttpClient(base_url="https://api.pinterest.com/v5/")
    fake.add("GET", f"pins/{PIN_ID}/analytics", PIN_ANALYTICS)
    fake.add("GET", f"pins/{PIN_ID}", IMAGE_PIN)
    fake.add("GET", "user_account/analytics", USER_ANALYTICS)
    fake.add("GET", "user_account", USER_ACCOUNT)
    fake.add("GET", "pins", PINS_PAGE)
    return fake


def make_adapter(
    fake: FakeHttpClient | None = None,
    config: dict | None = None,
    credentials: dict | None = None,
) -> PinterestSocialAdapter:
    return PinterestSocialAdapter(
        credentials=credentials or {"token": "test-token"},
        http_client=fake or make_fake_http(),
        config=config,
    )


@pytest.fixture
def fake_http() -> FakeHttpClient:
    return make_fake_http()


@pytest.fixture
def adapter(fake_http) -> PinterestSocialAdapter:
    return make_adapter(fake_http)


# ── Contract ──


class TestPinterestContract(SocialContractTests):
    """Run all social contract tests for Pinterest."""

    @pytest.fixture
    def adapter(self, fake_http) -> PinterestSocialAdapter:
        return make_adapter(fake_http)


# ── Account mapping ──


class TestAccountMapping:

    def test_fields(self):
        account = account_from_pinterest(USER_ACCOUNT)
        assert account.id == "1234567890"
        assert account.username == "cbsoft"
        assert account.profile_url == "https://www.pinterest.com/cbsoft/"
        assert account.avatar_url == "https://i.pinimg.com/avatars/cbsoft.jpg"
        assert account.description == "Building connectors."
        assert account.followers_count == 320
        assert account.following_count == 12
        assert account.posts_count == 87
        assert account.extra == {"monthly_views": 45000}

    def test_id_falls_back_to_username(self):
        user = {k: v for k, v in USER_ACCOUNT.items() if k != "id"}
        assert account_from_pinterest(user).id == "cbsoft"

    def test_pin_count_absent_is_none(self):
        user = {k: v for k, v in USER_ACCOUNT.items() if k != "pin_count"}
        assert account_from_pinterest(user).posts_count is None


# ── Pin mapping ──


class TestPinMapping:

    def test_image_pin(self):
        post = post_from_pin(IMAGE_PIN)
        assert post.id == PIN_ID
        assert post.url == f"https://www.pinterest.com/pin/{PIN_ID}/"
        assert post.title == "Summer #sale poster"
        assert post.description == "Our best #summer deals in one pin"
        assert post.media_type == SocialMediaType.IMAGE
        assert post.thumbnail_url == "https://i.pinimg.com/1200x/pin.jpg"  # best size
        assert post.hashtags == ["summer", "sale"]
        assert post.extra == {"board_id": "board-111"}

    def test_video_pin_with_null_text_fields(self):
        post = post_from_pin(VIDEO_PIN)
        assert post.media_type == SocialMediaType.VIDEO
        assert post.title == ""
        assert post.thumbnail_url == ""

    def test_unknown_media_type_is_other(self):
        pin = {**IMAGE_PIN, "media": {"media_type": "multiple_images", "images": {}}}
        assert post_from_pin(pin).media_type == SocialMediaType.OTHER

    def test_created_at_with_z_suffix(self):
        post = post_from_pin(IMAGE_PIN)
        assert post.published_at == datetime(2026, 6, 1, 10, 0, tzinfo=UTC)

    def test_created_at_naive_is_utc(self):
        post = post_from_pin(VIDEO_PIN)
        assert post.published_at == datetime(2026, 5, 20, 8, 30, tzinfo=UTC)

    def test_created_at_absent(self):
        pin = {k: v for k, v in IMAGE_PIN.items() if k != "created_at"}
        assert post_from_pin(pin).published_at is None

    def test_thumbnail_prefers_originals(self):
        pin = {
            **IMAGE_PIN,
            "media": {
                "media_type": "image",
                "images": {
                    "600x": {"url": "https://i.pinimg.com/600x/pin.jpg"},
                    "originals": {"url": "https://i.pinimg.com/originals/pin.jpg"},
                },
            },
        }
        assert post_from_pin(pin).thumbnail_url == "https://i.pinimg.com/originals/pin.jpg"

    def test_thumbnail_falls_back_to_any_size(self):
        pin = {
            **IMAGE_PIN,
            "media": {"media_type": "image", "images": {"236x": {"url": "https://i.pinimg.com/236x/pin.jpg"}}},
        }
        assert post_from_pin(pin).thumbnail_url == "https://i.pinimg.com/236x/pin.jpg"


# ── Analytics mapping ──


class TestPinAnalyticsMapping:

    def test_lifetime_metrics(self):
        stats = stats_from_pin_analytics(PIN_ID, PIN_ANALYTICS)
        assert stats.post_id == PIN_ID
        assert stats.impressions == 1000
        assert stats.saves == 25
        assert stats.clicks == 40 + 15  # PIN_CLICK + OUTBOUND_CLICK
        assert stats.extra == {"outbound_clicks": 15}

    def test_none_fields_rule(self):
        """Metrics Pinterest does not expose stay None — never 0."""
        stats = stats_from_pin_analytics(PIN_ID, PIN_ANALYTICS)
        assert stats.views is None
        assert stats.likes is None
        assert stats.comments is None
        assert stats.shares is None
        assert stats.reach is None

    def test_summary_metrics_key_tolerated(self):
        payload = {"all": {"summary_metrics": {"IMPRESSION": 500, "SAVE": 10}}}
        stats = stats_from_pin_analytics(PIN_ID, payload)
        assert stats.impressions == 500
        assert stats.saves == 10

    def test_pin_click_only(self):
        payload = {"all": {"lifetime_metrics": {"IMPRESSION": 100, "PIN_CLICK": 7}}}
        stats = stats_from_pin_analytics(PIN_ID, payload)
        assert stats.clicks == 7
        assert stats.extra == {}

    def test_empty_payload_is_all_none(self):
        stats = stats_from_pin_analytics(PIN_ID, {})
        assert stats.post_id == PIN_ID
        assert stats.impressions is None
        assert stats.saves is None
        assert stats.clicks is None

    def test_account_stats_mapping(self):
        stats = account_stats_from_analytics(USER_ANALYTICS, USER_ACCOUNT)
        assert stats.account_id == "1234567890"
        assert stats.followers_count == 320
        assert stats.following_count == 12
        assert stats.posts_count == 87
        assert stats.impressions == 5000
        assert stats.total_views is None
        assert stats.total_likes is None
        assert stats.extra == {"monthly_views": 45000}


# ── Adapter: pagination ──


class TestPagination:

    def test_bookmark_becomes_cursor(self, adapter):
        result = adapter.list_posts(limit=2)
        assert len(result.items) == 2
        assert result.cursor == "BOOKMARK_1"
        assert result.has_more is True

    def test_cursor_forwarded_as_bookmark_param(self, adapter, fake_http):
        adapter.list_posts(limit=10, cursor="BOOKMARK_1")
        call = fake_http.last_call()
        assert call.method == "GET"
        assert call.path == "pins"
        assert call.kwargs["params"] == {"page_size": 10, "bookmark": "BOOKMARK_1"}

    def test_first_page_sends_no_bookmark(self, adapter, fake_http):
        adapter.list_posts(limit=5)
        assert fake_http.last_call().kwargs["params"] == {"page_size": 5}

    @pytest.mark.parametrize("last_page", [
        {"items": [IMAGE_PIN], "bookmark": None},
        {"items": [IMAGE_PIN]},
    ])
    def test_last_page_has_no_cursor(self, last_page):
        fake = FakeHttpClient()
        fake.add("GET", "pins", last_page)
        result = make_adapter(fake).list_posts()
        assert result.cursor is None
        assert result.has_more is False


# ── Adapter: stats ──


class TestAdapterStats:

    def test_post_stats_uses_90_day_window(self, adapter, fake_http):
        stats = adapter.get_post_stats(PIN_ID)
        assert stats.post_id == PIN_ID
        assert stats.impressions == 1000

        call = fake_http.last_call()
        assert call.path == f"pins/{PIN_ID}/analytics"
        params = call.kwargs["params"]
        assert params["metric_types"] == "IMPRESSION,PIN_CLICK,OUTBOUND_CLICK,SAVE"
        start = date.fromisoformat(params["start_date"])
        end = date.fromisoformat(params["end_date"])
        assert (end - start).days == 90
        assert end == datetime.now(UTC).date()

    def test_account_stats_period_passthrough(self, adapter, fake_http):
        since = datetime(2026, 6, 1, tzinfo=UTC)
        until = datetime(2026, 6, 30, tzinfo=UTC)
        stats = adapter.get_account_stats(since=since, until=until)
        assert stats.period_start == since
        assert stats.period_end == until
        assert stats.followers_count == 320
        assert stats.impressions == 5000

        analytics_call = next(c for c in fake_http.calls if c.path == "user_account/analytics")
        assert analytics_call.kwargs["params"] == {"start_date": "2026-06-01", "end_date": "2026-06-30"}

    def test_account_stats_defaults_to_last_30_days(self, adapter, fake_http):
        adapter.get_account_stats()
        analytics_call = next(c for c in fake_http.calls if c.path == "user_account/analytics")
        params = analytics_call.kwargs["params"]
        start = date.fromisoformat(params["start_date"])
        end = date.fromisoformat(params["end_date"])
        assert (end - start).days == 30

    def test_get_post_not_found(self):
        fake = FakeHttpClient()
        fake.add("GET", f"pins/{PIN_ID}", {})
        with pytest.raises(PermanentProviderError):
            make_adapter(fake).get_post(PIN_ID)


# ── Publishing ──


class TestPublishPost:

    @pytest.fixture
    def draft(self) -> SocialPostDraft:
        return SocialPostDraft(
            title="Summer poster",
            description="Our best deals",
            media_type=SocialMediaType.IMAGE,
            media_url="https://cdn.example.com/poster.jpg",
            link="https://example.com/offer",
            extra={"board_id": "board-222"},
        )

    def test_image_pin_payload_with_board_from_extra(self, adapter, fake_http, draft):
        fake_http.add("POST", "pins", {"id": PIN_ID, "board_id": "board-222"})
        result = adapter.publish_post(draft)

        call = fake_http.last_call()
        assert call.method == "POST"
        assert call.path == "pins"
        assert call.kwargs["json"] == {
            "board_id": "board-222",
            "title": "Summer poster",
            "description": "Our best deals",
            "link": "https://example.com/offer",
            "media_source": {"source_type": "image_url", "url": "https://cdn.example.com/poster.jpg"},
        }
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == PIN_ID
        assert result.url == f"https://www.pinterest.com/pin/{PIN_ID}/"

    def test_board_from_config_default(self, draft):
        fake = make_fake_http()
        fake.add("POST", "pins", {"id": PIN_ID})
        adapter = make_adapter(fake, config={"default_board_id": "board-default"})
        adapter.publish_post(draft.model_copy(update={"extra": {}}))
        assert fake.last_call().kwargs["json"]["board_id"] == "board-default"

    def test_draft_board_wins_over_config_default(self, draft):
        fake = make_fake_http()
        fake.add("POST", "pins", {"id": PIN_ID})
        adapter = make_adapter(fake, config={"default_board_id": "board-default"})
        adapter.publish_post(draft)
        assert fake.last_call().kwargs["json"]["board_id"] == "board-222"

    def test_link_omitted_when_empty(self, adapter, fake_http, draft):
        fake_http.add("POST", "pins", {"id": PIN_ID})
        adapter.publish_post(draft.model_copy(update={"link": ""}))
        assert "link" not in fake_http.last_call().kwargs["json"]

    def test_missing_board_raises(self, adapter, draft):
        with pytest.raises(ValidationError, match="board"):
            adapter.publish_post(draft.model_copy(update={"extra": {}}))

    def test_image_without_media_url_raises(self, adapter, draft):
        with pytest.raises(ValidationError, match="media_url"):
            adapter.publish_post(draft.model_copy(update={"media_url": "", "file_path": "/tmp/poster.jpg"}))
        with pytest.raises(ValidationError, match="media_url"):
            adapter.publish_post(draft.model_copy(update={"media_url": "", "content": b"jpegbytes"}))

    @pytest.mark.parametrize("media_type", [SocialMediaType.VIDEO, SocialMediaType.SHORT_VIDEO])
    def test_video_raises(self, adapter, draft, media_type):
        with pytest.raises(ValidationError, match="media upload"):
            adapter.publish_post(draft.model_copy(update={"media_type": media_type}))

    def test_text_raises(self, adapter, draft):
        with pytest.raises(ValidationError, match="no text posts"):
            adapter.publish_post(draft.model_copy(update={"media_type": SocialMediaType.TEXT}))

    def test_check_publish_status_existing_pin_is_published(self, adapter):
        result = adapter.check_publish_status(PIN_ID)
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == PIN_ID
        assert result.publish_id == PIN_ID
        assert result.url == f"https://www.pinterest.com/pin/{PIN_ID}/"


# ── Capabilities ──


class TestCapabilities:

    def test_supports_social_publish(self, adapter):
        assert adapter.supports(SocialPublishCapability) is True

    def test_supports_oauth(self, adapter):
        assert adapter.supports(OAuthCapability) is True


# ── OAuth ──


OAUTH_SCOPES = ["user_accounts:read", "boards:read", "pins:read", "pins:write"]
EXPECTED_BASIC = "Basic " + b64encode(b"client-id-123:client-secret-456").decode()

TOKEN_RESPONSE = {
    "access_token": "ACCESS_TOKEN",
    "refresh_token": "REFRESH_TOKEN",
    "token_type": "bearer",
    "expires_in": 2592000,
    "refresh_token_expires_in": 31536000,
    "scope": " ".join(OAUTH_SCOPES),
}


class TestPinterestOAuth:

    def make_oauth_adapter(self, fake: FakeHttpClient | None = None) -> PinterestSocialAdapter:
        return make_adapter(
            fake or FakeHttpClient(),
            credentials={"client_id": "client-id-123", "client_secret": "client-secret-456"},
        )

    def test_oauth_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Pinterest"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["client_id", "client_secret"]
        assert manifest.auth.oauth.scopes == OAUTH_SCOPES

    def test_token_not_required_in_manifest(self):
        for name in ("token", "client_id", "client_secret"):
            credential = next(f for f in manifest.auth.required_fields if f.name == name)
            assert credential.required is False

    def test_validate_credentials(self):
        assert make_adapter().validate_credentials() is True  # token only
        assert self.make_oauth_adapter().validate_credentials() is True  # app credentials only
        empty = PinterestSocialAdapter(credentials={}, http_client=FakeHttpClient())
        assert empty.validate_credentials() is False

    def test_get_authorize_url(self):
        url = self.make_oauth_adapter().get_authorize_url("https://example.com/cb", state="xyz789")
        assert url.startswith("https://www.pinterest.com/oauth/?")
        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == ["client-id-123"]
        assert query["redirect_uri"] == ["https://example.com/cb"]
        assert query["response_type"] == ["code"]
        assert query["scope"] == [",".join(OAUTH_SCOPES)]
        assert query["state"] == ["xyz789"]

    def test_exchange_code_uses_basic_auth_header(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/token", TOKEN_RESPONSE)
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")

        call = fake.last_call()
        assert call.method == "POST"
        assert call.path == "https://api.pinterest.com/v5/oauth/token"
        assert call.kwargs["headers"] == {"Authorization": EXPECTED_BASIC}
        assert call.kwargs["data"] == {
            "grant_type": "authorization_code",
            "code": "the_code",
            "redirect_uri": "https://example.com/cb",
        }
        assert tokens.access_token == "ACCESS_TOKEN"
        assert tokens.refresh_token == "REFRESH_TOKEN"
        assert tokens.expires_in == 2592000
        assert tokens.extra["refresh_token_expires_in"] == 31536000
        assert tokens.extra["credentials"] == {
            "token": "ACCESS_TOKEN",
            "client_id": "client-id-123",
            "client_secret": "client-secret-456",
        }

    def test_refresh_token_uses_basic_auth_header(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/token", TOKEN_RESPONSE)
        tokens = self.make_oauth_adapter(fake).refresh_token("REFRESH_TOKEN")

        call = fake.last_call()
        assert call.kwargs["headers"] == {"Authorization": EXPECTED_BASIC}
        assert call.kwargs["data"] == {"grant_type": "refresh_token", "refresh_token": "REFRESH_TOKEN"}
        assert tokens.access_token == "ACCESS_TOKEN"
        assert tokens.refresh_token == "REFRESH_TOKEN"

    def test_refresh_keeps_refresh_token_when_response_omits_it(self):
        fake = FakeHttpClient()
        response = {k: v for k, v in TOKEN_RESPONSE.items() if k != "refresh_token"}
        fake.add("POST", "oauth/token", response)
        tokens = self.make_oauth_adapter(fake).refresh_token("OLD_REFRESH_TOKEN")
        # Pinterest keeps the same refresh token until it expires.
        assert tokens.refresh_token == "OLD_REFRESH_TOKEN"

    def test_token_error_raises_authentication_error(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/token", {"code": 283, "message": "Invalid code."})
        with pytest.raises(AuthenticationError, match="283"):
            self.make_oauth_adapter(fake).exchange_code_for_token("bad_code", "https://example.com/cb")


# ── Connection test ──


class TestConnection:

    def test_success_message_includes_username(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert "cbsoft" in result.message

    def test_failure(self):
        fake = FakeHttpClient()

        def boom(method, path, kwargs):
            raise AuthenticationError("Pinterest access token invalid")

        fake.add("GET", "user_account", boom)
        result = make_adapter(fake).test_connection()
        assert result.success is False
        assert "invalid" in result.message
