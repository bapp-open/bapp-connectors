"""
Facebook Page publishing: publish profile, Reels flow, hashtags in captions, place tagging.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import SocialLocationSearchCapability
from bapp_connectors.core.dto.social import (
    PublishStatus,
    SocialFormat,
    SocialLocation,
    SocialMediaType,
    SocialPostDraft,
)
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.core.social_profile import fit_draft
from bapp_connectors.providers.social.facebook.adapter import FacebookSocialAdapter
from tests.fake_http import FakeHttpClient

PAGE_ID = "P1"
MEDIA_URL = "https://media.bapp.ro/s/1.mp4"
RUPLOAD_URL = "https://rupload.facebook.com/video-upload/v19.0/V1"


def adapter(fake: FakeHttpClient) -> FacebookSocialAdapter:
    return FacebookSocialAdapter(credentials={"token": "PAGE_TOKEN", "page_id": PAGE_ID}, http_client=fake)


def reel_http() -> FakeHttpClient:
    fake = FakeHttpClient()

    def video_reels(method, path, kwargs):
        if kwargs["json"]["upload_phase"] == "start":
            return {"video_id": "V1", "upload_url": RUPLOAD_URL}
        return {"success": True}

    fake.add("POST", f"{PAGE_ID}/video_reels", video_reels)
    fake.add("POST", RUPLOAD_URL, {"success": True})
    return fake


def reel_draft(**overrides) -> SocialPostDraft:
    values = {
        "format": SocialFormat.REEL,
        "media_type": SocialMediaType.SHORT_VIDEO,
        "media_url": MEDIA_URL,
        "description": "Hi",
        "hashtags": ["x"],
    }
    values.update(overrides)
    return SocialPostDraft(**values)


class TestReels:
    def test_reel_uses_video_reels_flow(self):
        fake = reel_http()
        result = adapter(fake).publish_post(reel_draft(hashtags=["#x", "X"]))

        assert result.status == PublishStatus.PROCESSING
        assert result.publish_id == "V1"
        assert [c.path for c in fake.calls] == [f"{PAGE_ID}/video_reels", RUPLOAD_URL, f"{PAGE_ID}/video_reels"]
        assert fake.calls[0].kwargs["json"] == {"upload_phase": "start"}
        upload_headers = fake.calls[1].kwargs["headers"]
        assert upload_headers["file_url"] == MEDIA_URL
        assert upload_headers["Authorization"] == "OAuth PAGE_TOKEN"
        assert fake.calls[2].kwargs["json"] == {
            "upload_phase": "finish",
            "video_id": "V1",
            "video_state": "PUBLISHED",
            "description": "Hi\n\n#x",
        }

    def test_reel_without_media_url_is_rejected(self):
        fake = reel_http()
        with pytest.raises(ValidationError):
            adapter(fake).publish_post(reel_draft(media_url="", content=b"bytes", filename="a.mp4"))
        assert fake.calls == []

    def test_reel_status_published_when_publishing_phase_complete(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "V1",
            {
                "status": {"video_status": "ready", "publishing_phase": {"status": "complete"}},
                "permalink_url": "/reel/V1",
            },
        )
        result = adapter(fake).check_publish_status("V1")
        assert result.status == PublishStatus.PUBLISHED
        assert result.url == "https://www.facebook.com/reel/V1"

    def test_reel_status_processing_while_publishing_phase_pending(self):
        fake = FakeHttpClient()
        fake.add("GET", "V1", {"status": {"video_status": "ready", "publishing_phase": {"status": "in_progress"}}})
        assert adapter(fake).check_publish_status("V1").status == PublishStatus.PROCESSING

    def test_reel_status_failed_when_publishing_phase_errors(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "V1",
            {"status": {"video_status": "processing", "publishing_phase": {"status": "error"}}},
        )
        assert adapter(fake).check_publish_status("V1").status == PublishStatus.FAILED

    def test_failed_status_carries_meta_error_message(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "V1",
            {
                "status": {
                    "video_status": "error",
                    "processing_phase": {"status": "error", "error": {"message": "Video format not supported"}},
                }
            },
        )
        result = adapter(fake).check_publish_status("V1")
        assert result.status == PublishStatus.FAILED
        assert "Video format not supported" in result.error

    def test_failed_publishing_phase_carries_meta_error_message(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "V1",
            {
                "status": {
                    "video_status": "ready",
                    "publishing_phase": {"status": "error", "error": {"message": "Aspect ratio not allowed"}},
                }
            },
        )
        assert "Aspect ratio not allowed" in adapter(fake).check_publish_status("V1").error

    def test_reel_finish_success_false_is_failed(self):
        fake = FakeHttpClient()

        def video_reels(method, path, kwargs):
            if kwargs["json"]["upload_phase"] == "start":
                return {"video_id": "V1", "upload_url": RUPLOAD_URL}
            return {"success": False}

        fake.add("POST", f"{PAGE_ID}/video_reels", video_reels)
        fake.add("POST", RUPLOAD_URL, {"success": True})
        result = adapter(fake).publish_post(reel_draft())
        assert result.status == PublishStatus.FAILED
        assert result.publish_id == "V1"
        assert result.error


class TestCaptionAndPlace:
    def test_photo_caption_includes_hashtags_and_place(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/photos", {"id": "7", "post_id": f"{PAGE_ID}_7"})
        draft = SocialPostDraft(
            media_type=SocialMediaType.IMAGE,
            media_url="https://media.bapp.ro/p.jpg",
            description="Hi",
            hashtags=["#x"],
            location=SocialLocation(id="L1", name="Cluj"),
        )
        adapter(fake).publish_post(draft)
        payload = fake.last_call().kwargs["json"]
        assert payload["caption"] == "Hi\n\n#x"
        assert payload["place"] == "L1"

    def test_feed_message_includes_hashtags_and_place(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/feed", {"id": f"{PAGE_ID}_1"})
        draft = SocialPostDraft(
            media_type=SocialMediaType.TEXT,
            description="Hi",
            hashtags=["x", "y"],
            location=SocialLocation(id="L1", name="Cluj"),
        )
        adapter(fake).publish_post(draft)
        assert fake.last_call().kwargs["json"] == {"message": "Hi\n\n#x #y", "place": "L1"}

    def test_video_description_includes_hashtags(self):
        fake = FakeHttpClient()
        fake.add("POST", f"{PAGE_ID}/videos", {"id": "555"})
        draft = SocialPostDraft(media_type=SocialMediaType.VIDEO, media_url=MEDIA_URL, description="Hi", hashtags=["x"])
        adapter(fake).publish_post(draft)
        assert fake.last_call().kwargs["json"]["description"] == "Hi\n\n#x"


class TestPublishProfile:
    def test_publish_profile_formats(self):
        profile = adapter(FakeHttpClient()).get_publish_profile()
        assert [f.format for f in profile.formats] == [SocialFormat.POST, SocialFormat.REEL]

        post = profile.for_format(SocialFormat.POST)
        assert post.media_types == [SocialMediaType.IMAGE, SocialMediaType.VIDEO]
        assert post.max_text_length == 63206
        assert post.max_hashtags is None
        assert post.supports_location is True
        assert post.location_media_types == [SocialMediaType.IMAGE]
        assert not (post.supports_mentions or post.supports_product_tags or post.vertical_only or post.requires_title)

        reel = profile.for_format(SocialFormat.REEL)
        assert reel.media_types == [SocialMediaType.SHORT_VIDEO]
        assert reel.max_text_length == 2200
        assert (reel.min_video_seconds, reel.max_video_seconds) == (3, 90)
        assert reel.vertical_only is True
        assert reel.supports_location is False

    def test_fit_draft_drops_location_from_reels(self):
        profile = adapter(FakeHttpClient()).get_publish_profile()
        fitted = fit_draft(reel_draft(location=SocialLocation(id="L1", name="Cluj")), profile, video_seconds=30)
        assert fitted.errors == []
        assert fitted.omitted == ["location"]

    def test_fit_draft_keeps_location_on_post_image_and_text(self):
        profile = adapter(FakeHttpClient()).get_publish_profile()
        location = SocialLocation(id="L1", name="Cluj")
        image = SocialPostDraft(media_type=SocialMediaType.IMAGE, media_url="https://m/p.jpg", location=location)
        text = SocialPostDraft(media_type=SocialMediaType.TEXT, description="Hi", location=location)
        for draft in (image, text):
            fitted = fit_draft(draft, profile)
            assert fitted.omitted == []
            assert fitted.draft.location == location

    def test_fit_draft_drops_location_from_post_video(self):
        # /videos takes no `place`: the location is dropped and reported, not lost silently
        profile = adapter(FakeHttpClient()).get_publish_profile()
        draft = SocialPostDraft(
            media_type=SocialMediaType.VIDEO, media_url=MEDIA_URL, location=SocialLocation(id="L1", name="Cluj")
        )
        fitted = fit_draft(draft, profile, video_seconds=30)
        assert fitted.errors == []
        assert fitted.omitted == ["location"]
        assert fitted.draft.location is None

    def test_location_search_not_declared(self):
        # pages/search needs the "Page Public Metadata Access" feature (app review), see adapter docstring.
        assert not isinstance(adapter(FakeHttpClient()), SocialLocationSearchCapability)
