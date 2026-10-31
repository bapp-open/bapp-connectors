"""
Instagram publishing: publish profile, user/product tags, location, mention and product search.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import (
    SocialLocationSearchCapability,
    SocialMentionSearchCapability,
    SocialProductSearchCapability,
)
from bapp_connectors.core.dto.social import (
    PublishStatus,
    SocialFormat,
    SocialLocation,
    SocialMediaType,
    SocialMention,
    SocialPostDraft,
    SocialProductTag,
)
from bapp_connectors.core.errors import PermanentProviderError, ProviderError, ValidationError
from bapp_connectors.core.social_profile import fit_draft
from bapp_connectors.providers.social.instagram.adapter import InstagramSocialAdapter
from tests.fake_http import FakeHttpClient

IG_USER_ID = "IG1"
IMAGE_URL = "https://media.bapp.ro/p.jpg"
VIDEO_URL = "https://media.bapp.ro/r.mp4"

USER_NOT_FOUND = {
    "error": {
        "message": "Invalid user id",
        "type": "OAuthException",
        "code": 110,
        "error_subcode": 2207013,
        "error_user_title": "Cannot find User",
    }
}


def adapter(fake: FakeHttpClient) -> InstagramSocialAdapter:
    return InstagramSocialAdapter(credentials={"token": "T", "ig_user_id": IG_USER_ID}, http_client=fake)


def publish_http() -> FakeHttpClient:
    fake = FakeHttpClient()
    fake.add("POST", f"{IG_USER_ID}/media_publish", {"id": "M1"})
    fake.add("POST", f"{IG_USER_ID}/media", {"id": "C1"})
    return fake


TAGS = {
    "hashtags": ["#x", "X", "y"],
    "mentions": [SocialMention(username="ana"), SocialMention(username="bob")],
    "product_tags": [SocialProductTag(id="P1"), SocialProductTag(id="P2")],
    "location": SocialLocation(id="L1", name="Cluj"),
}


class TestImagePost:
    def test_image_container_carries_tags_and_location(self):
        fake = publish_http()
        draft = SocialPostDraft(media_type=SocialMediaType.IMAGE, media_url=IMAGE_URL, description="Hi", **TAGS)
        result = adapter(fake).publish_post(draft)

        assert result.status == PublishStatus.PUBLISHED
        assert fake.calls[0].path == f"{IG_USER_ID}/media"
        assert fake.calls[0].kwargs["json"] == {
            "image_url": IMAGE_URL,
            "caption": "Hi\n\n#x #y",
            "user_tags": [{"username": "ana", "x": 0.5, "y": 0.5}, {"username": "bob", "x": 0.5, "y": 0.5}],
            "product_tags": [{"product_id": "P1", "x": 0.5, "y": 0.5}, {"product_id": "P2", "x": 0.5, "y": 0.5}],
            "location_id": "L1",
        }

    def test_image_without_tags_sends_only_url_and_caption(self):
        fake = publish_http()
        adapter(fake).publish_post(SocialPostDraft(media_type=SocialMediaType.IMAGE, media_url=IMAGE_URL))
        assert fake.calls[0].kwargs["json"] == {"image_url": IMAGE_URL, "caption": ""}

    def test_image_without_media_url_is_rejected(self):
        fake = publish_http()
        with pytest.raises(ValidationError):
            adapter(fake).publish_post(SocialPostDraft(media_type=SocialMediaType.IMAGE, description="Hi"))
        assert fake.calls == []


class TestReel:
    def test_reel_container_shares_to_feed_with_tags_and_location(self):
        fake = publish_http()
        draft = SocialPostDraft(
            format=SocialFormat.REEL,
            media_type=SocialMediaType.SHORT_VIDEO,
            media_url=VIDEO_URL,
            description="Hi",
            **TAGS,
        )
        result = adapter(fake).publish_post(draft)

        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == "C1"
        assert [c.path for c in fake.calls] == [f"{IG_USER_ID}/media"]
        assert fake.calls[0].kwargs["json"] == {
            "media_type": "REELS",
            "video_url": VIDEO_URL,
            "share_to_feed": True,
            "caption": "Hi\n\n#x #y",
            "user_tags": [{"username": "ana"}, {"username": "bob"}],
            "product_tags": [{"product_id": "P1"}, {"product_id": "P2"}],
            "location_id": "L1",
        }

    def test_reel_with_image_is_rejected(self):
        fake = publish_http()
        draft = SocialPostDraft(format=SocialFormat.REEL, media_type=SocialMediaType.IMAGE, media_url=IMAGE_URL)
        with pytest.raises(ValidationError):
            adapter(fake).publish_post(draft)
        assert fake.calls == []


class TestSearchMentions:
    def test_exact_username_returns_one_account(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            IG_USER_ID,
            {
                "business_discovery": {
                    "id": "99",
                    "username": "bapp.ro",
                    "name": "BAPP",
                    "profile_picture_url": "https://cdn/p.jpg",
                },
                "id": IG_USER_ID,
            },
        )
        result = adapter(fake).search_mentions("@bapp.ro")

        assert result == [SocialMention(username="bapp.ro", id="99", name="BAPP", avatar_url="https://cdn/p.jpg")]
        assert fake.last_call().path == IG_USER_ID
        assert fake.last_call().kwargs["params"] == {
            "fields": "business_discovery.username(bapp.ro){username,name,profile_picture_url}"
        }

    def test_user_not_found_in_200_body_returns_empty(self):
        fake = FakeHttpClient()
        fake.add("GET", IG_USER_ID, USER_NOT_FOUND)
        assert adapter(fake).search_mentions("nu_exista") == []

    def test_user_not_found_http_400_returns_empty(self):
        fake = FakeHttpClient()

        def not_found(method, path, kwargs):
            raise PermanentProviderError(
                'Client error: 400 {"error":{"message":"Invalid user id","type":"OAuthException","code":110,'
                '"error_subcode":2207013}}',
                status_code=400,
            )

        fake.add("GET", IG_USER_ID, not_found)
        assert adapter(fake).search_mentions("nu_exista") == []

    def test_other_errors_propagate(self):
        fake = FakeHttpClient()
        fake.add("GET", IG_USER_ID, {"error": {"message": "boom", "code": 2}})
        with pytest.raises(ProviderError):
            adapter(fake).search_mentions("bapp.ro")

    def test_blank_query_makes_no_call(self):
        fake = FakeHttpClient()
        assert adapter(fake).search_mentions(" @ ") == []
        assert fake.calls == []

    @pytest.mark.parametrize(
        "query",
        ["bapp){id}", "a b", "user,name", "x" * 31, "ana(1)", "@"],
    )
    def test_invalid_username_makes_no_call(self, query):
        fake = FakeHttpClient()
        assert adapter(fake).search_mentions(query) == []
        assert fake.calls == []


class TestSearchProducts:
    def test_blank_query_makes_no_call(self):
        fake = FakeHttpClient()
        assert adapter(fake).search_products("  ") == []
        assert fake.calls == []

    def test_searches_first_catalog(self):
        fake = FakeHttpClient()
        fake.add("GET", f"{IG_USER_ID}/available_catalogs", {"data": [{"catalog_id": "K1"}, {"catalog_id": "K2"}]})
        fake.add(
            "GET",
            f"{IG_USER_ID}/catalog_product_search",
            {
                "data": [
                    {
                        "product_id": 11,
                        "product_name": "Mug",
                        "image_url": "https://cdn/m.jpg",
                        "retailer_id": "SKU1",
                        "review_status": "approved",
                    },
                    {"product_id": 12, "product_name": "Cup"},
                ]
            },
        )
        result = adapter(fake).search_products("mu", limit=1)

        assert result == [
            SocialProductTag(
                id="11",
                name="Mug",
                image_url="https://cdn/m.jpg",
                extra={"retailer_id": "SKU1", "review_status": "approved"},
            )
        ]
        assert fake.last_call().kwargs["params"] == {"catalog_id": "K1", "q": "mu"}

    def test_no_catalog_returns_empty(self):
        fake = FakeHttpClient()
        fake.add("GET", f"{IG_USER_ID}/available_catalogs", {"data": []})
        assert adapter(fake).search_products("mu") == []
        assert len(fake.calls) == 1


class TestPublishProfile:
    def test_publish_profile_formats(self):
        profile = adapter(FakeHttpClient()).get_publish_profile()
        assert [f.format for f in profile.formats] == [SocialFormat.POST, SocialFormat.REEL]

        post = profile.for_format(SocialFormat.POST)
        assert post.media_types == [SocialMediaType.IMAGE]
        assert (post.max_text_length, post.max_hashtags, post.max_mentions) == (2200, 30, 20)
        assert post.supports_mentions and post.supports_product_tags and post.supports_location
        assert not post.vertical_only

        reel = profile.for_format(SocialFormat.REEL)
        assert reel.media_types == [SocialMediaType.SHORT_VIDEO]
        assert (reel.max_text_length, reel.max_hashtags, reel.max_mentions) == (2200, 30, 20)
        assert reel.supports_mentions and reel.supports_product_tags and reel.supports_location
        assert (reel.min_video_seconds, reel.max_video_seconds) == (3, 90)
        assert reel.vertical_only is True

    def test_fit_draft_keeps_tags_on_reel(self):
        profile = adapter(FakeHttpClient()).get_publish_profile()
        draft = SocialPostDraft(
            format=SocialFormat.REEL, media_type=SocialMediaType.SHORT_VIDEO, media_url=VIDEO_URL, **TAGS
        )
        fitted = fit_draft(draft, profile, video_seconds=30)
        assert fitted.errors == []
        assert fitted.omitted == []

    def test_capabilities(self):
        ig = adapter(FakeHttpClient())
        assert isinstance(ig, SocialMentionSearchCapability)
        assert isinstance(ig, SocialProductSearchCapability)
        # Same rule as Facebook: place search needs "Page Public Metadata Access" (app review).
        assert not isinstance(ig, SocialLocationSearchCapability)
