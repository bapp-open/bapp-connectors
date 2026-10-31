from bapp_connectors.core.dto.social import (
    SocialFormat,
    SocialFormatProfile,
    SocialLocation,
    SocialMediaType,
    SocialMention,
    SocialPostDraft,
    SocialProductTag,
    SocialPublishProfile,
)
from bapp_connectors.core.social_profile import compose_caption, fit_draft

REEL = SocialFormatProfile(
    format=SocialFormat.REEL,
    media_types=[SocialMediaType.SHORT_VIDEO],
    max_text_length=20,
    max_hashtags=2,
    min_video_seconds=3,
    max_video_seconds=90,
)
POST = SocialFormatProfile(
    format=SocialFormat.POST,
    media_types=[SocialMediaType.IMAGE],
    supports_location=True,
    supports_mentions=True,
    max_mentions=1,
)
PROFILE = SocialPublishProfile(formats=[POST, REEL])


def test_unsupported_fields_are_dropped_and_reported():
    d = SocialPostDraft(
        format=SocialFormat.REEL,
        media_type=SocialMediaType.SHORT_VIDEO,
        description="hi",
        mentions=[SocialMention(username="a")],
        product_tags=[SocialProductTag(id="1")],
        location=SocialLocation(id="9", name="Cluj"),
    )
    fitted = fit_draft(d, PROFILE, video_seconds=10)
    assert fitted.errors == []
    assert fitted.draft.mentions == [] and fitted.draft.product_tags == [] and fitted.draft.location is None
    assert sorted(fitted.omitted) == ["location", "mentions", "product_tags"]


def test_hashtags_over_limit_are_cut_and_reported():
    d = SocialPostDraft(format=SocialFormat.REEL, media_type=SocialMediaType.SHORT_VIDEO, hashtags=["a", "b", "c"])
    fitted = fit_draft(d, PROFILE, video_seconds=10)
    assert fitted.draft.hashtags == ["a", "b"] and fitted.omitted == ["hashtags"]


def test_mentions_over_limit_are_cut():
    d = SocialPostDraft(
        format=SocialFormat.POST,
        media_type=SocialMediaType.IMAGE,
        mentions=[SocialMention(username="a"), SocialMention(username="b")],
    )
    fitted = fit_draft(d, PROFILE)
    assert [m.username for m in fitted.draft.mentions] == ["a"] and fitted.omitted == ["mentions"]


def test_text_too_long_is_an_error_not_a_cut():
    d = SocialPostDraft(
        format=SocialFormat.REEL, media_type=SocialMediaType.SHORT_VIDEO, description="x" * 15, hashtags=["abcdef"]
    )
    # lungimea se măsoară pe compose_caption(description, hashtags) = 15 + 2 + 7 = 24 > 20
    assert "text_too_long" in fit_draft(d, PROFILE, video_seconds=10).errors


def test_format_and_media_type_errors():
    assert fit_draft(SocialPostDraft(format=SocialFormat.SHORT), PROFILE).errors == ["format_unsupported"]
    d = SocialPostDraft(format=SocialFormat.REEL, media_type=SocialMediaType.IMAGE)
    assert "media_type_unsupported" in fit_draft(d, PROFILE).errors


def test_video_duration_bounds():
    d = SocialPostDraft(format=SocialFormat.REEL, media_type=SocialMediaType.SHORT_VIDEO)
    assert "video_too_short" in fit_draft(d, PROFILE, video_seconds=2).errors
    assert "video_too_long" in fit_draft(d, PROFILE, video_seconds=91).errors
    assert fit_draft(d, PROFILE, video_seconds=None).errors == []  # durată necunoscută = nu se verifică


def test_compose_caption_dedupes_and_normalizes():
    assert compose_caption("Salut", ["#vara", "vara", " reduceri "]) == "Salut\n\n#vara #reduceri"
    assert compose_caption("", ["a"]) == "#a"
    assert compose_caption("Salut", []) == "Salut"


def test_default_publish_profile_is_empty():
    from bapp_connectors.core.capabilities import SocialPublishCapability

    class X(SocialPublishCapability):
        def publish_post(self, draft): ...
        def check_publish_status(self, publish_id): ...

    assert X().get_publish_profile().formats == []


def test_empty_fields_are_not_reported_as_omitted():
    d = SocialPostDraft(format=SocialFormat.REEL, media_type=SocialMediaType.SHORT_VIDEO, hashtags=["a", "#a", "b"])
    fitted = fit_draft(d, PROFILE, video_seconds=10)
    assert fitted.omitted == [] and fitted.errors == [] and fitted.draft is d


def test_zero_hashtags_removes_all():
    profile = SocialPublishProfile(
        formats=[SocialFormatProfile(format=SocialFormat.POST, media_types=[SocialMediaType.IMAGE], max_hashtags=0)]
    )
    d = SocialPostDraft(media_type=SocialMediaType.IMAGE, hashtags=["a"])
    fitted = fit_draft(d, profile)
    assert fitted.draft.hashtags == [] and fitted.omitted == ["hashtags"]


def test_title_rules():
    def profile(**kw):
        fmt = SocialFormatProfile(format=SocialFormat.POST, media_types=[SocialMediaType.IMAGE], **kw)
        return SocialPublishProfile(formats=[fmt])

    d = SocialPostDraft(media_type=SocialMediaType.IMAGE, title="Titlu")
    fitted = fit_draft(d, profile(max_title_length=0))
    assert fitted.draft.title == "" and fitted.omitted == ["title"] and fitted.errors == []
    assert fit_draft(d, profile(max_title_length=3)).errors == ["title_too_long"]
    no_title = SocialPostDraft(media_type=SocialMediaType.IMAGE)
    assert fit_draft(no_title, profile(requires_title=True)).errors == ["title_required"]


def test_for_format_and_new_oauth_field():
    from bapp_connectors.core.capabilities import OAuthTokens

    assert PROFILE.for_format(SocialFormat.REEL) is REEL
    assert PROFILE.for_format(SocialFormat.SHORT) is None
    assert OAuthTokens(access_token="t").refresh_expires_in is None
