# Connecting Threads (social)

Reads a Threads profile, posts, and insights, and publishes threads, via
Meta's **Threads API** (graph.threads.net).

| | |
|---|---|
| Provider key | `social` / `threads` |
| Auth | Threads user access token (Bearer) |
| Credentials | `token`; `app_id` + `app_secret` for OAuth |
| Settings | — |
| Capabilities | `SocialPublishCapability`, `OAuthCapability` |

## What you get

- `get_account()` — username, name, bio, avatar (followers via user insights)
- `list_posts()` / `get_post()` — the user's threads (text/image/video/carousel)
- `get_post_stats()` — views, likes, replies (as comments), shares; reposts/quotes in `extra`
- `get_account_stats(since, until)` — followers, total views/likes over the period
- `publish_post()` — text, image, and video threads

## Getting credentials

1. Create an app at [developers.facebook.com](https://developers.facebook.com/apps/)
   and add the **Threads API** use case. Threads apps use their own app ID
   (shown under the Threads use case settings) — that's your `app_id`/`app_secret`.
2. Request scopes: `threads_basic`, `threads_content_publish`,
   `threads_manage_insights`.
3. Run the OAuth flow — the adapter implements it (Threads-native, on
   threads.net): `get_authorize_url` → `exchange_code_for_token`, which
   performs the short-lived exchange **and** the `th_exchange_token` upgrade to
   a long-lived token (~60 days) in one call. The Threads user id is surfaced
   in `tokens.extra`.
4. Refresh with `refresh_token(current_token)` — Threads refreshes the access
   token itself via `th_refresh_token` (there is no separate refresh token).

## Quick start

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.threads  # noqa: F401

adapter = registry.create_adapter("social", "threads", credentials={"token": "TH..."})

for post in adapter.list_posts(limit=10).items:
    stats = adapter.get_post_stats(post.id)
    print(post.description[:50], stats.views, stats.likes, stats.comments)
```

## Publishing

```python
from bapp_connectors.core.dto.social import PublishStatus, SocialMediaType, SocialPostDraft

# Text thread — published immediately (container + threads_publish two-step)
adapter.publish_post(SocialPostDraft(description="Hello Threads!",
                                     media_type=SocialMediaType.TEXT))

# Video — async; check_publish_status performs the final publish when ready
result = adapter.publish_post(SocialPostDraft(description="Watch this",
                                              media_url="https://cdn.example.com/clip.mp4"))
while result.status == PublishStatus.PROCESSING:
    result = adapter.check_publish_status(result.publish_id)
```

- Media is **URL-based** (Meta fetches `media_url`); local files/bytes raise
  `ValidationError`.

## Notes & limitations

- Publishing is capped by Meta (~250 posts per 24h per profile).
- Carousel threads and reply management are not wrapped yet.
