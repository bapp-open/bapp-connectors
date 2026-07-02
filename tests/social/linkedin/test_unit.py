"""
LinkedIn Page social provider unit tests — no network, canned REST responses.

Runs the SocialPort contract suite against a FakeHttpClient plus
provider-specific tests: Rest.li protocol headers, offset pagination,
share statistics mapping, publishing payload shapes, and the OAuth flow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.dto.social import (
    PublishStatus,
    SocialMediaType,
    SocialPostDraft,
    SocialPrivacy,
)
from bapp_connectors.core.errors import PermanentProviderError, ProviderError, ValidationError
from bapp_connectors.providers.social.linkedin.adapter import LinkedInSocialAdapter
from bapp_connectors.providers.social.linkedin.errors import first_element_or_not_found
from bapp_connectors.providers.social.linkedin.manifest import manifest
from bapp_connectors.providers.social.linkedin.mappers import (
    account_from_org,
    org_urn,
    post_from_linkedin,
    stats_from_share_stats,
)
from tests.fake_http import FakeHttpClient
from tests.social.contract import SocialContractTests

ORG_ID = "2414183"
ORG_URN = f"urn:li:organization:{ORG_ID}"
ORG_URN_ENCODED = "urn%3Ali%3Aorganization%3A2414183"
POST_ID = "urn:li:share:123"
POST_ID_ENCODED = "urn%3Ali%3Ashare%3A123"

CREATED_AT_MS = 1780308000000  # 2026-06-01T10:00:00Z

# ── Canned LinkedIn REST responses ──

ORG_OBJECT = {
    "id": 2414183,
    "vanityName": "test-co",
    "localizedName": "Test Co",
    "localizedDescription": "We test things.",
}

NETWORK_SIZES = {"firstDegreeSize": 5400}

POST_OBJECT = {
    "id": POST_ID,
    "author": ORG_URN,
    "commentary": "Big #summer #sale is live!",
    "createdAt": CREATED_AT_MS,
    "visibility": "PUBLIC",
    "lifecycleState": "PUBLISHED",
}

VIDEO_POST_OBJECT = {
    "id": "urn:li:ugcPost:456",
    "author": ORG_URN,
    "commentary": "Watch our new video",
    "createdAt": CREATED_AT_MS,
    "content": {"media": {"id": "urn:li:video:789", "title": "Clip"}},
}

ARTICLE_POST_OBJECT = {
    "id": "urn:li:share:321",
    "author": ORG_URN,
    "commentary": "Read our blog",
    "createdAt": CREATED_AT_MS,
    "content": {"article": {"source": "https://example.com/blog", "title": "Blog"}},
}

POSTS_LIST = {
    "elements": [POST_OBJECT, VIDEO_POST_OBJECT],
    "paging": {"start": 0, "count": 2, "total": 5},
}

SHARE_STATS = {
    "elements": [
        {
            "totalShareStatistics": {
                "impressionCount": 1000,
                "likeCount": 50,
                "commentCount": 10,
                "shareCount": 5,
                "clickCount": 80,
                "engagement": 0.145,
            },
            "organizationalEntity": ORG_URN,
        },
    ],
}

NEW_POST_URN = "urn:li:share:999"


def fake_create_response(headers: dict | None = None, ok: bool = True) -> SimpleNamespace:
    """Fake requests.Response for POST posts (direct_response=True)."""
    return SimpleNamespace(
        ok=ok,
        status_code=201 if ok else 422,
        headers={"x-restli-id": NEW_POST_URN} if headers is None else headers,
        text="",
    )


def make_fake_http() -> FakeHttpClient:
    """FakeHttpClient with canned LinkedIn responses (matched by path substring)."""
    fake = FakeHttpClient()
    fake.add("GET", "organizationalEntityShareStatistics", SHARE_STATS)
    fake.add("GET", "networkSizes/", NETWORK_SIZES)
    fake.add("GET", f"organizations/{ORG_ID}", ORG_OBJECT)
    fake.add("GET", "posts?q=author", POSTS_LIST)
    fake.add("GET", f"posts/{POST_ID_ENCODED}", POST_OBJECT)
    fake.add("POST", "posts", fake_create_response())
    return fake


def make_adapter(fake: FakeHttpClient | None = None, config: dict | None = None) -> LinkedInSocialAdapter:
    return LinkedInSocialAdapter(
        credentials={"access_token": "test_token", "organization_id": ORG_ID},
        http_client=fake or make_fake_http(),
        config=config,
    )


# ── Contract ──


class TestLinkedInContract(SocialContractTests):

    @pytest.fixture
    def adapter(self) -> LinkedInSocialAdapter:
        return make_adapter()

    @pytest.fixture
    def sample_post_id(self) -> str:
        return POST_ID


# ── Rest.li protocol headers ──


class TestRestliHeaders:

    def test_headers_sent_on_every_call(self):
        fake = make_fake_http()
        make_adapter(fake).get_account()
        assert fake.calls
        for call in fake.calls:
            headers = call.kwargs["headers"]
            assert headers["Authorization"] == "Bearer test_token"
            assert headers["X-Restli-Protocol-Version"] == "2.0.0"
            assert headers["LinkedIn-Version"] == "202405"  # manifest default

    def test_version_setting_overrides_header(self):
        fake = make_fake_http()
        make_adapter(fake, config={"linkedin_version": "202506"}).get_account()
        assert fake.calls[0].kwargs["headers"]["LinkedIn-Version"] == "202506"

    def test_urns_are_percent_encoded_in_paths(self):
        fake = make_fake_http()
        adapter = make_adapter(fake)
        adapter.get_account()
        adapter.get_post(POST_ID)
        adapter.get_post_stats(POST_ID)
        paths = [call.path for call in fake.calls]
        assert f"networkSizes/{ORG_URN_ENCODED}?edgeType=COMPANY_FOLLOWED_BY_MEMBER" in paths
        assert f"posts/{POST_ID_ENCODED}" in paths
        assert any(f"organizationalEntity={ORG_URN_ENCODED}&shares[0]={POST_ID_ENCODED}" in path for path in paths)


# ── Pagination ──


class TestPagination:

    def test_first_page_has_more_and_offset_cursor(self):
        result = make_adapter().list_posts(limit=2)
        assert len(result.items) == 2
        assert result.has_more is True  # 0 + 2 < 5
        assert result.cursor == "2"
        assert result.total == 5

    def test_offset_round_trip(self):
        fake = FakeHttpClient()
        fake.add("GET", "start=2", {
            "elements": [ARTICLE_POST_OBJECT],
            "paging": {"start": 2, "count": 1, "total": 3},
        })
        fake.add("GET", "posts?q=author", {
            "elements": [POST_OBJECT, VIDEO_POST_OBJECT],
            "paging": {"start": 0, "count": 2, "total": 3},
        })
        adapter = make_adapter(fake)

        page1 = adapter.list_posts(limit=2)
        assert page1.has_more is True
        assert page1.cursor == "2"

        page2 = adapter.list_posts(limit=2, cursor=page1.cursor)
        assert [post.id for post in page2.items] == [ARTICLE_POST_OBJECT["id"]]
        assert page2.has_more is False  # 2 + 1 == 3
        assert page2.cursor is None

        assert f"posts?q=author&author={ORG_URN_ENCODED}&count=2&start=2" in fake.last_call().path

    def test_last_page_when_total_reached(self):
        fake = FakeHttpClient()
        fake.add("GET", "posts?q=author", {
            "elements": [POST_OBJECT],
            "paging": {"start": 0, "count": 1, "total": 1},
        })
        result = make_adapter(fake).list_posts(limit=25)
        assert result.has_more is False
        assert result.cursor is None


# ── Post mapping ──


class TestPostMapping:

    def test_fields(self):
        post = post_from_linkedin(POST_OBJECT)
        assert post.id == POST_ID
        assert post.account_id == ORG_ID
        assert post.url == f"https://www.linkedin.com/feed/update/{POST_ID}/"
        assert post.description == "Big #summer #sale is live!"
        assert post.hashtags == ["summer", "sale"]
        assert post.published_at == datetime.fromtimestamp(CREATED_AT_MS / 1000, tz=UTC)

    def test_plain_post_is_text(self):
        assert post_from_linkedin(POST_OBJECT).media_type == SocialMediaType.TEXT

    def test_video_media(self):
        assert post_from_linkedin(VIDEO_POST_OBJECT).media_type == SocialMediaType.VIDEO

    def test_image_media(self):
        post = {**POST_OBJECT, "content": {"media": {"id": "urn:li:image:42"}}}
        assert post_from_linkedin(post).media_type == SocialMediaType.IMAGE

    def test_unknown_media_is_other(self):
        post = {**POST_OBJECT, "content": {"media": {"id": "urn:li:document:42"}}}
        assert post_from_linkedin(post).media_type == SocialMediaType.OTHER

    def test_article_is_text_with_link_in_extra(self):
        post = post_from_linkedin(ARTICLE_POST_OBJECT)
        assert post.media_type == SocialMediaType.TEXT
        assert post.extra["article_url"] == "https://example.com/blog"

    def test_account_mapping(self):
        account = account_from_org(ORG_OBJECT, 5400)
        assert account.id == ORG_ID
        assert account.username == "test-co"
        assert account.display_name == "Test Co"
        assert account.profile_url == "https://www.linkedin.com/company/test-co/"
        assert account.description == "We test things."
        assert account.followers_count == 5400

    def test_org_urn_helper(self):
        assert org_urn(ORG_ID) == ORG_URN


# ── Stats mapping ──


class TestStatsMapping:

    def test_share_stats_fields(self):
        stats = stats_from_share_stats(SHARE_STATS["elements"][0], post_id=POST_ID)
        assert stats.post_id == POST_ID
        assert stats.impressions == 1000
        assert stats.likes == 50
        assert stats.comments == 10
        assert stats.shares == 5
        assert stats.clicks == 80
        assert stats.engagement_rate == pytest.approx(0.145)
        assert stats.views is None  # LinkedIn tracks video views separately

    def test_adapter_sets_post_id(self):
        stats = make_adapter().get_post_stats(POST_ID)
        assert stats.post_id == POST_ID
        assert stats.impressions == 1000

    def test_empty_elements_raises_permanent_error(self):
        fake = make_fake_http()
        fake.responses.insert(0, ("GET", "organizationalEntityShareStatistics", {"elements": []}))
        with pytest.raises(PermanentProviderError):
            make_adapter(fake).get_post_stats(POST_ID)

    def test_first_element_or_not_found_helper(self):
        element = {"totalShareStatistics": {}}
        assert first_element_or_not_found({"elements": [element]}, "share statistics", POST_ID) is element
        with pytest.raises(PermanentProviderError):
            first_element_or_not_found({"elements": []}, "share statistics", POST_ID)
        with pytest.raises(PermanentProviderError):
            first_element_or_not_found({}, "share statistics", POST_ID)


# ── Account stats ──


class TestAccountStats:

    def test_followers_and_lifetime_aggregates(self):
        stats = make_adapter().get_account_stats()
        assert stats.account_id == ORG_ID
        assert stats.followers_count == 5400
        assert stats.impressions == 1000
        assert stats.engagement_rate == pytest.approx(0.145)
        assert stats.extra == {"likes": 50, "comments": 10, "shares": 5, "clicks": 80}

    def test_period_passthrough_without_filtering(self):
        since = datetime(2026, 6, 1, tzinfo=UTC)
        until = datetime(2026, 6, 30, tzinfo=UTC)
        fake = make_fake_http()
        stats = make_adapter(fake).get_account_stats(since=since, until=until)
        assert stats.period_start == since
        assert stats.period_end == until
        stats_call = next(c for c in fake.calls if "organizationalEntityShareStatistics" in c.path)
        assert "shares[" not in stats_call.path  # org-level, no shares filter


# ── Publishing ──


class TestPublishPost:

    def test_text_post_payload_and_result(self):
        fake = make_fake_http()
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT, description="Hello LinkedIn")
        result = make_adapter(fake).publish_post(draft)

        call = fake.last_call()
        assert call.method == "POST"
        assert call.path == "posts"
        assert call.kwargs["json"] == {
            "author": ORG_URN,
            "commentary": "Hello LinkedIn",
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == NEW_POST_URN
        assert result.publish_id == NEW_POST_URN
        assert result.url == f"https://www.linkedin.com/feed/update/{NEW_POST_URN}/"

    def test_article_link_post_payload(self):
        fake = make_fake_http()
        draft = SocialPostDraft(
            media_type=SocialMediaType.TEXT,
            title="Our blog",
            description="Read this",
            link="https://example.com/blog",
        )
        make_adapter(fake).publish_post(draft)

        payload = fake.last_call().kwargs["json"]
        assert payload["commentary"] == "Read this"
        assert payload["content"] == {"article": {"source": "https://example.com/blog", "title": "Our blog"}}

    def test_link_only_post_uses_link_as_title(self):
        fake = make_fake_http()
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT, link="https://example.com/blog")
        make_adapter(fake).publish_post(draft)
        payload = fake.last_call().kwargs["json"]
        assert payload["content"]["article"]["title"] == "https://example.com/blog"

    def test_non_public_privacy_raises(self):
        draft = SocialPostDraft(
            media_type=SocialMediaType.TEXT,
            description="Secret",
            privacy=SocialPrivacy.PRIVATE,
        )
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    @pytest.mark.parametrize(
        "media_source",
        [
            {"media_url": "https://cdn.example.com/clip.mp4"},
            {"file_path": "/tmp/clip.mp4"},
            {"content": b"videobytes"},
        ],
    )
    def test_media_draft_raises_validation_error(self, media_source):
        draft = SocialPostDraft(media_type=SocialMediaType.VIDEO, description="A clip", **media_source)
        with pytest.raises(ValidationError, match="initializeUpload"):
            make_adapter().publish_post(draft)

    def test_empty_draft_raises(self):
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT)
        with pytest.raises(ValidationError):
            make_adapter().publish_post(draft)

    def test_missing_restli_id_header_raises(self):
        fake = FakeHttpClient()
        fake.add("POST", "posts", fake_create_response(headers={}))
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT, description="Hello")
        with pytest.raises(ProviderError):
            make_adapter(fake).publish_post(draft)

    def test_not_ok_response_raises(self):
        fake = FakeHttpClient()
        fake.add("POST", "posts", fake_create_response(ok=False))
        draft = SocialPostDraft(media_type=SocialMediaType.TEXT, description="Hello")
        with pytest.raises(ProviderError):
            make_adapter(fake).publish_post(draft)

    def test_check_publish_status_is_published(self):
        result = make_adapter().check_publish_status(POST_ID)
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == POST_ID
        assert result.url == f"https://www.linkedin.com/feed/update/{POST_ID}/"


# ── Capabilities ──


class TestCapabilities:

    def test_supports_social_publish(self):
        assert make_adapter().supports(SocialPublishCapability) is True

    def test_supports_oauth(self):
        assert make_adapter().supports(OAuthCapability) is True


# ── OAuth ──


OAUTH_SCOPES = ["r_organization_social", "w_organization_social", "rw_organization_admin"]


class TestLinkedInOAuth:

    def make_oauth_adapter(self, fake: FakeHttpClient | None = None) -> LinkedInSocialAdapter:
        return LinkedInSocialAdapter(
            credentials={"client_id": "app_123", "client_secret": "app_secret_456", "organization_id": ORG_ID},
            http_client=fake or FakeHttpClient(),
        )

    def test_oauth_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with LinkedIn"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["client_id", "client_secret"]
        assert manifest.auth.oauth.scopes == OAUTH_SCOPES

    def test_access_token_not_required_in_manifest(self):
        token_field = next(f for f in manifest.auth.required_fields if f.name == "access_token")
        assert token_field.required is False
        org_field = next(f for f in manifest.auth.required_fields if f.name == "organization_id")
        assert org_field.required is True

    def test_get_authorize_url(self):
        url = self.make_oauth_adapter().get_authorize_url("https://example.com/cb", state="xyz789")
        assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
        assert "scope=r_organization_social%20w_organization_social%20rw_organization_admin" in url
        query = parse_qs(urlparse(url).query)
        assert query["response_type"] == ["code"]
        assert query["client_id"] == ["app_123"]
        assert query["redirect_uri"] == ["https://example.com/cb"]
        assert query["state"] == ["xyz789"]
        assert query["scope"] == [" ".join(OAUTH_SCOPES)]

    def test_exchange_code_for_token(self):
        fake = FakeHttpClient()
        fake.add(
            "POST",
            "oauth/v2/accessToken",
            {
                "access_token": "NEW_TOKEN",
                "expires_in": 5184000,
                "refresh_token": "REFRESH_TOKEN",
                "refresh_token_expires_in": 31536000,
            },
        )
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")

        call = fake.last_call()
        assert call.method == "POST"
        assert call.path == "https://www.linkedin.com/oauth/v2/accessToken"
        assert call.kwargs["data"] == {
            "grant_type": "authorization_code",
            "code": "the_code",
            "client_id": "app_123",
            "client_secret": "app_secret_456",
            "redirect_uri": "https://example.com/cb",
        }
        assert tokens.access_token == "NEW_TOKEN"
        assert tokens.refresh_token == "REFRESH_TOKEN"
        assert tokens.expires_in == 5184000
        assert tokens.extra["refresh_token_expires_in"] == 31536000
        assert tokens.extra["credentials"] == {
            "access_token": "NEW_TOKEN",
            "client_id": "app_123",
            "client_secret": "app_secret_456",
        }

    def test_exchange_without_refresh_token_is_tolerated(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/v2/accessToken", {"access_token": "NEW_TOKEN", "expires_in": 5184000})
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")
        assert tokens.access_token == "NEW_TOKEN"
        assert tokens.refresh_token == ""  # only Marketing partners get refresh tokens

    def test_refresh_token_grant(self):
        fake = FakeHttpClient()
        fake.add(
            "POST",
            "oauth/v2/accessToken",
            {"access_token": "REFRESHED_TOKEN", "expires_in": 5184000, "refresh_token": "NEW_REFRESH"},
        )
        tokens = self.make_oauth_adapter(fake).refresh_token("OLD_REFRESH")

        assert fake.last_call().kwargs["data"] == {
            "grant_type": "refresh_token",
            "refresh_token": "OLD_REFRESH",
            "client_id": "app_123",
            "client_secret": "app_secret_456",
        }
        assert tokens.access_token == "REFRESHED_TOKEN"
        assert tokens.refresh_token == "NEW_REFRESH"


# ── Credentials & connection ──


class TestCredentialsAndConnection:

    def test_access_token_plus_org_id_is_valid(self):
        assert make_adapter().validate_credentials() is True

    def test_client_credentials_only_is_valid(self):
        adapter = LinkedInSocialAdapter(
            credentials={"client_id": "app_123", "client_secret": "app_secret_456"},
            http_client=FakeHttpClient(),
        )
        assert adapter.validate_credentials() is True

    def test_missing_everything_is_invalid(self):
        adapter = LinkedInSocialAdapter(credentials={"organization_id": ORG_ID}, http_client=FakeHttpClient())
        assert adapter.validate_credentials() is False

    def test_access_token_without_org_id_is_invalid(self):
        adapter = LinkedInSocialAdapter(credentials={"access_token": "tok"}, http_client=FakeHttpClient())
        assert adapter.validate_credentials() is False

    def test_connection_success_includes_org_name(self):
        result = make_adapter().test_connection()
        assert result.success is True
        assert "Test Co" in result.message

    def test_connection_failure(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            f"organizations/{ORG_ID}",
            lambda m, p, k: (_ for _ in ()).throw(ProviderError("boom")),
        )
        result = make_adapter(fake).test_connection()
        assert result.success is False
