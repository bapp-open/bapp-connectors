"""
Threads social provider unit tests — no network, canned Threads API responses.

Runs the SocialPort contract suite against a FakeHttpClient plus
provider-specific tests: insights parsing (both payload shapes), stats
mapping, pagination, media type mapping, the two-step publish flow, the
Threads-specific OAuth flow, and error classification.
"""

from __future__ import annotations

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
    ProviderError,
    RateLimitError,
    ValidationError,
)
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.threads.adapter import ThreadsSocialAdapter
from bapp_connectors.providers.social.threads.errors import check_payload, classify_threads_error
from bapp_connectors.providers.social.threads.manifest import manifest
from bapp_connectors.providers.social.threads.mappers import (
    account_from_threads,
    account_stats_from_insights,
    insights_to_dict,
    post_from_threads,
    post_stats_from_insights,
)
from tests.fake_http import FakeHttpClient
from tests.social.contract import SocialContractTests

USER_ID = "24316979840"
MEDIA_ID = "18000000000000001"
TEXT_MEDIA_ID = "18000000000000002"

# ── Canned Threads API responses ──

ME_OBJECT = {
    "id": USER_ID,
    "username": "testuser",
    "name": "Test User",
    "threads_profile_picture_url": "https://cdn.example.com/avatar.jpg",
    "threads_biography": "A profile for testing.",
}

IMAGE_MEDIA_OBJECT = {
    "id": MEDIA_ID,
    "text": "Big #summer #sale is live!",
    "media_type": "IMAGE",
    "media_url": "https://cdn.example.com/pic.jpg",
    "permalink": "https://www.threads.net/@testuser/post/AAA111",
    "timestamp": "2026-06-01T10:00:00+0000",
    "username": "testuser",
    "is_quote_post": False,
}

TEXT_MEDIA_OBJECT = {
    "id": TEXT_MEDIA_ID,
    "text": "Just a plain thought",
    "media_type": "TEXT_POST",
    "permalink": "https://www.threads.net/@testuser/post/BBB222",
    "timestamp": "2026-06-02T12:30:00+0000",
    "username": "testuser",
    "is_quote_post": False,
}

THREADS_EDGE = {
    "data": [IMAGE_MEDIA_OBJECT, TEXT_MEDIA_OBJECT],
    "paging": {
        "cursors": {"before": "BEFORE_CURSOR", "after": "AFTER_CURSOR"},
        "next": "https://graph.threads.net/v1.0/me/threads?after=AFTER_CURSOR",
    },
}

MEDIA_INSIGHTS = {
    "data": [
        {"name": "views", "period": "lifetime", "values": [{"value": 100}]},
        {"name": "likes", "period": "lifetime", "values": [{"value": 10}]},
        {"name": "replies", "period": "lifetime", "values": [{"value": 2}]},
        {"name": "reposts", "period": "lifetime", "values": [{"value": 3}]},
        {"name": "quotes", "period": "lifetime", "values": [{"value": 1}]},
        {"name": "shares", "period": "lifetime", "values": [{"value": 4}]},
    ],
}

USER_INSIGHTS = {
    "data": [
        {"name": "views", "period": "day", "values": [{"value": 10}, {"value": 20}]},
        {"name": "likes", "period": "day", "total_value": {"value": 50}},
        {"name": "replies", "period": "day", "total_value": {"value": 7}},
        {"name": "reposts", "period": "day", "total_value": {"value": 5}},
        {"name": "quotes", "period": "day", "total_value": {"value": 2}},
        {"name": "followers_count", "period": "day", "total_value": {"value": 1500}},
    ],
}


def make_fake_http() -> FakeHttpClient:
    """FakeHttpClient with canned Threads responses (most specific paths first)."""
    fake = FakeHttpClient()
    fake.add("GET", f"{MEDIA_ID}/insights", MEDIA_INSIGHTS)
    fake.add("GET", MEDIA_ID, IMAGE_MEDIA_OBJECT)
    fake.add("GET", "me/threads_insights", USER_INSIGHTS)
    fake.add("GET", "me/threads", THREADS_EDGE)
    fake.add("GET", "me", ME_OBJECT)
    return fake


def make_adapter(fake: FakeHttpClient | None = None) -> ThreadsSocialAdapter:
    return ThreadsSocialAdapter(
        credentials={"token": "test_threads_token"},
        http_client=fake or make_fake_http(),
    )


# ── Contract ──


class TestThreadsContract(SocialContractTests):

    @pytest.fixture
    def adapter(self) -> ThreadsSocialAdapter:
        return make_adapter()

    @pytest.fixture
    def sample_post_id(self) -> str:
        return MEDIA_ID


# ── Insights parsing ──


class TestInsightsParsing:

    def test_values_shape(self):
        payload = {"data": [{"name": "views", "values": [{"value": 100}]}]}
        assert insights_to_dict(payload) == {"views": 100}

    def test_total_value_shape(self):
        payload = {"data": [{"name": "likes", "total_value": {"value": 50}}]}
        assert insights_to_dict(payload) == {"likes": 50}

    def test_series_values_are_summed(self):
        payload = {"data": [{"name": "views", "values": [{"value": 10}, {"value": 20}]}]}
        assert insights_to_dict(payload) == {"views": 30}

    def test_mixed_shapes(self):
        assert insights_to_dict(USER_INSIGHTS) == {
            "views": 30,
            "likes": 50,
            "replies": 7,
            "reposts": 5,
            "quotes": 2,
            "followers_count": 1500,
        }

    def test_empty_payload(self):
        assert insights_to_dict({}) == {}
        assert insights_to_dict({"data": [{"name": "views", "values": []}]}) == {}


# ── Post stats ──


class TestPostStats:

    def test_maps_universal_metrics(self):
        stats = post_stats_from_insights(MEDIA_ID, MEDIA_INSIGHTS)
        assert stats.post_id == MEDIA_ID
        assert stats.views == 100
        assert stats.likes == 10
        assert stats.comments == 2  # replies
        assert stats.shares == 4
        assert stats.extra == {"reposts": 3, "quotes": 1}
        assert stats.impressions is None

    def test_shares_falls_back_to_reposts_when_absent(self):
        payload = {"data": [m for m in MEDIA_INSIGHTS["data"] if m["name"] != "shares"]}
        stats = post_stats_from_insights(MEDIA_ID, payload)
        assert stats.shares == 3  # reposts
        assert stats.extra == {"reposts": 3, "quotes": 1}

    def test_none_payload_yields_all_none_stats(self):
        stats = post_stats_from_insights(MEDIA_ID, None)
        assert stats.post_id == MEDIA_ID
        assert stats.views is None
        assert stats.likes is None
        assert stats.comments is None
        assert stats.shares is None

    def test_adapter_tolerates_insights_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", f"{MEDIA_ID}/insights", lambda m, p, k: (_ for _ in ()).throw(ProviderError("boom")))
        stats = make_adapter(fake).get_post_stats(MEDIA_ID)
        assert stats.post_id == MEDIA_ID
        assert stats.views is None


# ── Account & account stats ──


class TestAccountMapping:

    def test_fields(self):
        account = account_from_threads(ME_OBJECT)
        assert account.id == USER_ID
        assert account.username == "testuser"
        assert account.display_name == "Test User"
        assert account.profile_url == "https://www.threads.net/@testuser"
        assert account.avatar_url == "https://cdn.example.com/avatar.jpg"
        assert account.description == "A profile for testing."
        assert account.followers_count is None  # not on the profile object

    def test_adapter_fills_followers_from_user_insights(self):
        account = make_adapter().get_account()
        assert account.followers_count == 1500

    def test_adapter_tolerates_followers_insights_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", "me/threads_insights", lambda m, p, k: (_ for _ in ()).throw(ProviderError("boom")))
        fake.add("GET", "me", ME_OBJECT)
        account = make_adapter(fake).get_account()
        assert account.id == USER_ID
        assert account.followers_count is None


class TestAccountStats:

    def test_maps_user_insights(self):
        stats = make_adapter().get_account_stats()
        assert stats.followers_count == 1500
        assert stats.total_views == 30  # daily series summed
        assert stats.total_likes == 50
        assert stats.extra == {"replies": 7, "reposts": 5, "quotes": 2}

    def test_mapper_without_followers_metric(self):
        payload = {"data": [{"name": "views", "values": [{"value": 10}]}]}
        stats = account_stats_from_insights(payload)
        assert stats.followers_count is None
        assert stats.total_views == 10

    def test_period_passthrough_as_unix_timestamps(self):
        from datetime import UTC, datetime

        since = datetime(2026, 6, 1, tzinfo=UTC)
        until = datetime(2026, 6, 30, tzinfo=UTC)
        fake = make_fake_http()
        stats = make_adapter(fake).get_account_stats(since=since, until=until)
        assert stats.period_start == since
        assert stats.period_end == until
        insights_call = next(c for c in fake.calls if "threads_insights" in c.path)
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
        fake.add("GET", "me/threads", {
            "data": [IMAGE_MEDIA_OBJECT],
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

    @pytest.mark.parametrize(
        ("threads_type", "expected"),
        [
            ("TEXT_POST", SocialMediaType.TEXT),
            ("IMAGE", SocialMediaType.IMAGE),
            ("VIDEO", SocialMediaType.VIDEO),
            ("CAROUSEL_ALBUM", SocialMediaType.CAROUSEL),
            ("REPOST_FACADE", SocialMediaType.OTHER),
            ("AUDIO", SocialMediaType.OTHER),  # unknown type
        ],
    )
    def test_mapping(self, threads_type: str, expected: SocialMediaType):
        media = {**IMAGE_MEDIA_OBJECT, "media_type": threads_type}
        assert post_from_threads(media).media_type == expected


# ── Post mapping ──


class TestPostMapping:

    def test_fields(self):
        post = post_from_threads(IMAGE_MEDIA_OBJECT)
        assert post.id == MEDIA_ID
        assert post.url == "https://www.threads.net/@testuser/post/AAA111"
        assert post.description == "Big #summer #sale is live!"
        assert post.media_url == "https://cdn.example.com/pic.jpg"
        assert post.hashtags == ["summer", "sale"]
        assert post.published_at is not None
        assert post.published_at.year == 2026
        assert post.extra["username"] == "testuser"
        assert post.extra["is_quote_post"] is False

    def test_missing_timestamp_is_none(self):
        media = {k: v for k, v in IMAGE_MEDIA_OBJECT.items() if k != "timestamp"}
        assert post_from_threads(media).published_at is None


# ── Error classification ──


class TestThreadsErrors:

    def test_code_190_is_authentication_error(self):
        error = classify_threads_error({"error": {"code": 190, "message": "Invalid OAuth access token."}})
        assert isinstance(error, AuthenticationError)

    @pytest.mark.parametrize("code", [4, 17, 32, 613])
    def test_throttling_codes_are_rate_limit_errors(self, code):
        error = classify_threads_error({"error": {"code": code, "message": "Too many calls."}})
        assert isinstance(error, RateLimitError)

    def test_code_100_is_validation_error(self):
        error = classify_threads_error({"error": {"code": 100, "message": "Unsupported field."}})
        assert isinstance(error, ValidationError)

    def test_unknown_code_is_provider_error(self):
        error = classify_threads_error({"error": {"code": 1, "message": "Unknown error."}})
        assert isinstance(error, ProviderError)
        assert "Unknown error." in str(error)

    def test_check_payload_raises_on_error_body(self):
        with pytest.raises(AuthenticationError):
            check_payload({"error": {"code": 190, "message": "expired"}})

    def test_check_payload_passes_clean_body(self):
        payload = {"id": USER_ID, "username": "testuser"}
        assert check_payload(payload) is payload

    def test_client_raises_on_error_in_200_body(self):
        fake = FakeHttpClient()
        fake.add("GET", "me", {"error": {"code": 190, "message": "expired token"}})
        with pytest.raises(AuthenticationError):
            make_adapter(fake).get_account()


# ── Publishing ──


CREATION_ID = "17900000000000001"
PUBLISHED_ID = "18000000000000009"


def make_publish_fake() -> FakeHttpClient:
    """FakeHttpClient for the two-step container flow (publish edge first: substring matching)."""
    fake = FakeHttpClient()
    fake.add("POST", "me/threads_publish", {"id": PUBLISHED_ID})
    fake.add("POST", "me/threads", {"id": CREATION_ID})
    return fake


class TestPublishPost:

    def test_text_post_is_immediate_two_step(self):
        fake = make_publish_fake()
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT, description="Hello Threads")
        result = make_adapter(fake).publish_post(draft)

        assert len(fake.calls) == 2
        container_call, publish_call = fake.calls
        assert container_call.method == "POST"
        assert container_call.path == "me/threads"
        assert container_call.kwargs["params"] == {"media_type": "TEXT", "text": "Hello Threads"}
        assert publish_call.path == "me/threads_publish"
        assert publish_call.kwargs["params"] == {"creation_id": CREATION_ID}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == PUBLISHED_ID
        assert result.publish_id == CREATION_ID

    def test_text_post_without_text_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT)
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_image_post_is_immediate_two_step(self):
        fake = make_publish_fake()
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            media_url="https://cdn.example.com/pic.jpg",
            description="Nice pic",
        )
        result = make_adapter(fake).publish_post(draft)

        assert len(fake.calls) == 2
        assert fake.calls[0].kwargs["params"] == {
            "media_type": "IMAGE",
            "text": "Nice pic",
            "image_url": "https://cdn.example.com/pic.jpg",
        }
        assert fake.calls[1].kwargs["params"] == {"creation_id": CREATION_ID}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == PUBLISHED_ID

    def test_video_post_returns_processing(self):
        fake = make_publish_fake()
        draft = SocialPostDraft(
            media_type=SocialMediaType.VIDEO,
            media_url="https://cdn.example.com/clip.mp4",
            description="A clip",
        )
        result = make_adapter(fake).publish_post(draft)

        assert len(fake.calls) == 1  # no threads_publish call yet
        assert fake.calls[0].path == "me/threads"
        assert fake.calls[0].kwargs["params"] == {
            "media_type": "VIDEO",
            "text": "A clip",
            "video_url": "https://cdn.example.com/clip.mp4",
        }
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == CREATION_ID
        assert result.post_id == ""

    def test_image_without_media_url_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.IMAGE, description="No media")
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_local_media_content_raises(self):
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            content=b"jpegbytes",
            filename="pic.jpg",
        )
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_local_media_file_path_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.VIDEO, file_path="/tmp/clip.mp4")
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_unsupported_media_type_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.CAROUSEL, description="Album")
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_extra_is_merged_into_container_params_last(self):
        fake = make_publish_fake()
        draft = SocialPostDraft(
            media_type=SocialMediaType.TEXT,
            description="Limited replies",
            extra={"reply_control": "mentioned_only"},
        )
        make_adapter(fake).publish_post(draft)
        assert fake.calls[0].kwargs["params"]["reply_control"] == "mentioned_only"


class TestCheckPublishStatus:

    def _fake_with_container(self, container: dict) -> FakeHttpClient:
        fake = FakeHttpClient()
        fake.add("POST", "me/threads_publish", {"id": PUBLISHED_ID})
        fake.add("GET", CREATION_ID, container)
        return fake

    def test_finished_publishes_and_reports_published(self):
        fake = self._fake_with_container({"id": CREATION_ID, "status": "FINISHED"})
        result = make_adapter(fake).check_publish_status(CREATION_ID)

        publish_call = fake.last_call()
        assert publish_call.method == "POST"
        assert publish_call.path == "me/threads_publish"
        assert publish_call.kwargs["params"] == {"creation_id": CREATION_ID}
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == PUBLISHED_ID
        assert result.publish_id == CREATION_ID

    def test_in_progress_stays_processing(self):
        fake = self._fake_with_container({"id": CREATION_ID, "status": "IN_PROGRESS"})
        result = make_adapter(fake).check_publish_status(CREATION_ID)
        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == CREATION_ID
        assert len(fake.calls) == 1  # no publish attempt

    def test_error_is_failed_with_error_message(self):
        fake = self._fake_with_container(
            {"id": CREATION_ID, "status": "ERROR", "error_message": "Video too long"}
        )
        result = make_adapter(fake).check_publish_status(CREATION_ID)
        assert result.status == PublishStatus.FAILED
        assert result.error == "Video too long"

    def test_expired_is_failed(self):
        fake = self._fake_with_container({"id": CREATION_ID, "status": "EXPIRED"})
        result = make_adapter(fake).check_publish_status(CREATION_ID)
        assert result.status == PublishStatus.FAILED
        assert result.error != ""


# ── Capabilities ──


class TestCapabilities:

    def test_supports_all_declared_capabilities(self):
        adapter = make_adapter()
        assert adapter.supports(SocialPort) is True
        assert adapter.supports(SocialPublishCapability) is True
        assert adapter.supports(OAuthCapability) is True


# ── OAuth ──


OAUTH_SCOPES = ["threads_basic", "threads_content_publish", "threads_manage_insights"]


class TestThreadsOAuth:

    def make_oauth_adapter(self, fake: FakeHttpClient | None = None) -> ThreadsSocialAdapter:
        return ThreadsSocialAdapter(
            credentials={"app_id": "app_123", "app_secret": "app_secret_456"},
            http_client=fake or FakeHttpClient(),
        )

    def test_oauth_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Threads"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["app_id", "app_secret"]
        assert manifest.auth.oauth.scopes == OAUTH_SCOPES

    def test_token_not_required_in_manifest(self):
        for name in ("token", "app_id", "app_secret"):
            credential_field = next(f for f in manifest.auth.required_fields if f.name == name)
            assert credential_field.required is False

    def test_validate_credentials(self):
        assert make_adapter().validate_credentials() is True  # token only
        assert self.make_oauth_adapter().validate_credentials() is True  # app credentials only
        empty = ThreadsSocialAdapter(credentials={}, http_client=FakeHttpClient())
        assert empty.validate_credentials() is False

    def test_get_authorize_url_is_on_threads_net(self):
        url = self.make_oauth_adapter().get_authorize_url("https://example.com/cb", state="xyz789")
        assert url.startswith("https://threads.net/oauth/authorize?")
        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == ["app_123"]
        assert query["redirect_uri"] == ["https://example.com/cb"]
        assert query["response_type"] == ["code"]
        assert query["state"] == ["xyz789"]
        assert query["scope"] == [",".join(OAUTH_SCOPES)]

    def test_exchange_code_is_short_then_long_lived(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/access_token", {"access_token": "SHORT_TOKEN", "user_id": 24316979840})
        fake.add(
            "GET",
            "access_token",
            {"access_token": "LONG_TOKEN", "token_type": "bearer", "expires_in": 5183944},
        )
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")

        assert len(fake.calls) == 2
        short_call, long_call = fake.calls
        assert short_call.method == "POST"
        assert short_call.path == "https://graph.threads.net/oauth/access_token"
        assert short_call.kwargs["data"] == {
            "client_id": "app_123",
            "client_secret": "app_secret_456",
            "grant_type": "authorization_code",
            "redirect_uri": "https://example.com/cb",
            "code": "the_code",
        }
        assert long_call.method == "GET"
        assert long_call.path == "https://graph.threads.net/access_token"
        assert long_call.kwargs["params"] == {
            "grant_type": "th_exchange_token",
            "client_secret": "app_secret_456",
            "access_token": "SHORT_TOKEN",
        }
        assert tokens.access_token == "LONG_TOKEN"
        assert tokens.refresh_token == ""  # Threads has no refresh tokens
        assert tokens.expires_in == 5183944
        assert tokens.extra["user_id"] == "24316979840"
        assert tokens.extra["credentials"] == {
            "token": "LONG_TOKEN",
            "app_id": "app_123",
            "app_secret": "app_secret_456",
        }

    def test_refresh_token_uses_th_refresh_token_grant(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "refresh_access_token",
            {"access_token": "REFRESHED_TOKEN", "token_type": "bearer", "expires_in": 5184000},
        )
        tokens = self.make_oauth_adapter(fake).refresh_token("CURRENT_LONG_TOKEN")

        call = fake.last_call()
        assert call.method == "GET"
        assert call.path == "https://graph.threads.net/refresh_access_token"
        assert call.kwargs["params"] == {
            "grant_type": "th_refresh_token",
            "access_token": "CURRENT_LONG_TOKEN",
        }
        assert tokens.access_token == "REFRESHED_TOKEN"
        assert tokens.refresh_token == ""
        assert tokens.expires_in == 5184000
        assert tokens.extra["credentials"]["token"] == "REFRESHED_TOKEN"

    def test_exchange_raises_on_error_body(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/access_token", {"error": {"code": 100, "message": "Invalid code"}})
        with pytest.raises(ValidationError):
            self.make_oauth_adapter(fake).exchange_code_for_token("bad_code", "https://example.com/cb")


# ── Connection test ──


class TestConnection:

    def test_success_message_includes_username(self):
        result = make_adapter().test_connection()
        assert result.success is True
        assert "testuser" in result.message

    def test_failure(self):
        fake = FakeHttpClient()
        fake.add("GET", "me", {"error": {"code": 190, "message": "expired token"}})
        result = make_adapter(fake).test_connection()
        assert result.success is False
