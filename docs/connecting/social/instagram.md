# Connecting Instagram (social)

Reads an Instagram **Business/Creator** account's profile, media, and insights,
and publishes posts/Reels, via the **Instagram Graph API** (graph.facebook.com v19.0).

| | |
|---|---|
| Provider key | `social` / `instagram` |
| Auth | Meta access token (Bearer) |
| Credentials | `token`, `ig_user_id`; `app_id` + `app_secret` for OAuth |
| Settings | — |
| Capabilities | `SocialPublishCapability`, `OAuthCapability` |

## What you get

- `get_account()` — username, name, bio, avatar, follower/following/media counts
- `list_posts()` / `get_post()` — media with type mapping (image/video/carousel; Reels → `SHORT_VIDEO`)
- `get_post_stats()` — likes, comments + impressions, reach, saves; video plays for video media
- `get_account_stats(since, until)` — followers + daily impressions/reach summed over the period
- `publish_post()` — images and Reels (see below)

> **Ads note:** you don't need a separate provider to *advertise* on Instagram —
> Instagram placements are bought through the Meta Marketing API, i.e. the
> `ads/facebook` provider.

## Getting credentials

Instagram API access goes **through a Facebook Page** linked to the Instagram
Business/Creator account:

1. Convert the Instagram account to Business/Creator and link it to a Facebook
   Page (Instagram app → Settings → Business tools).
2. Create a Business-type app at
   [developers.facebook.com](https://developers.facebook.com/apps/) and request:
   `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`,
   `pages_show_list`.
3. Run the OAuth flow — the adapter implements it (add `app_id` + `app_secret`):
   `get_authorize_url` → `exchange_code_for_token` → then call
   **`list_instagram_accounts(user_token)`** — it returns
   `{page_id, page_name, page_token, ig_user_id}` for each Page with a linked
   Instagram account. Store the `page_token` as `token` and the `ig_user_id`.
4. `refresh_token(current_token)` runs Meta's long-lived `fb_exchange_token`
   exchange (~60 days; Meta has no refresh tokens).

## Quick start

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.instagram  # noqa: F401

adapter = registry.create_adapter(
    "social", "instagram",
    credentials={"token": "EAAB...", "ig_user_id": "17841400000000000"},
)

for post in adapter.list_posts(limit=10).items:
    stats = adapter.get_post_stats(post.id)
    print(post.media_type, stats.likes, stats.impressions, stats.saves)
```

## Publishing

Instagram publishing is **URL-based** — Meta fetches the media from a public
URL (`media_url`); local files/bytes are rejected, and there are no text-only
posts.

```python
from bapp_connectors.core.dto.social import PublishStatus, SocialMediaType, SocialPostDraft

# Image — published immediately (container + media_publish two-step)
adapter.publish_post(SocialPostDraft(description="New drop #launch",
                                     media_type=SocialMediaType.IMAGE,
                                     media_url="https://cdn.example.com/photo.jpg"))

# Reel — async while Meta transcodes; check_publish_status performs the final publish
result = adapter.publish_post(SocialPostDraft(description="BTS 🎬",
                                              media_url="https://cdn.example.com/reel.mp4"))
while result.status == PublishStatus.PROCESSING:
    result = adapter.check_publish_status(result.publish_id)
```

## Notes & limitations

- Only **Business/Creator** accounts work — personal Instagram accounts have no
  API access.
- Publishing is rate-limited by Meta to ~50 posts per 24h per account.
- Story publishing and carousel creation are not wrapped yet.
