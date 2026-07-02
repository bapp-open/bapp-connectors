# Connecting Facebook Page (social)

Reads a Facebook **Page**'s profile, posts (including Reels as they appear on
the posts edge), and engagement/insights via the **Graph API v19.0**.

| | |
|---|---|
| Provider key | `social` / `facebook` |
| Auth | Page access token (Bearer) |
| Credentials | `token`, `page_id` |
| Settings | — |
| Capabilities | `SocialPublishCapability` |

## What you get

- `get_account()` — page name, username, link, avatar, follower count
- `list_posts()` / `get_post()` — page posts with media type detection (video/photo/album/text)
- `get_post_stats()` — likes, comments, shares from the post + impressions,
  reach, clicks, video views from post insights
- `get_account_stats(since, until)` — followers + page impressions/reach summed
  over the period

## Getting credentials

1. Create an app of type **Business** at
   [developers.facebook.com](https://developers.facebook.com/apps/).
2. You must have a role (admin/editor) on the Page you want to connect.
3. Request these permissions (App Review is required for production use):
   - `pages_show_list` — list your pages
   - `pages_read_engagement` — posts, likes, comments, shares
   - `read_insights` — post & page insights (impressions, reach)
   - `pages_manage_posts` — only if you use `publish_post`
4. Get a **Page access token**:
   - Quick test: [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
     → select your app → *Get Page Access Token* → pick the page.
   - Production: run Facebook Login for a page admin, then call
     `GET /me/accounts` — each entry contains the page `id` and its page
     `access_token`. Exchange the user token for a long-lived one first
     (`GET /oauth/access_token?grant_type=fb_exchange_token&...`) so the page
     token is long-lived too.
5. Use the page token as `token` and the page's numeric ID as `page_id`.

> **Token lifetime:** page tokens derived from a long-lived user token do not
> expire on a fixed schedule but are invalidated by password changes/permission
> revocation. `test_connection()` is a cheap validity check.

## Quick start

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.facebook  # noqa: F401

adapter = registry.create_adapter(
    "social", "facebook",
    credentials={"token": "EAAB...", "page_id": "123456789012345"},
)

page = adapter.list_posts(limit=10)
for post in page.items:
    stats = adapter.get_post_stats(post.id)
    print(post.description[:50], stats.likes, stats.impressions, stats.reach)

from datetime import datetime, timedelta
week = adapter.get_account_stats(since=datetime.now() - timedelta(days=7), until=datetime.now())
print("Weekly impressions:", week.impressions, "reach:", week.reach)
```

## Publishing

```python
from bapp_connectors.core.dto.social import PublishStatus, SocialMediaType, SocialPostDraft

# Text / link post — published immediately
adapter.publish_post(SocialPostDraft(description="Big news!", link="https://example.com",
                                     media_type=SocialMediaType.TEXT))

# Photo — from a URL or a local file
adapter.publish_post(SocialPostDraft(description="New arrivals",
                                     media_type=SocialMediaType.IMAGE,
                                     media_url="https://cdn.example.com/photo.jpg"))

# Video — async while Meta transcodes
result = adapter.publish_post(SocialPostDraft(title="Launch", description="…",
                                              media_url="https://cdn.example.com/clip.mp4"))
while result.status == PublishStatus.PROCESSING:
    result = adapter.check_publish_status(result.publish_id)
```

- Pages publish **publicly** — a non-public `privacy` is rejected. Use
  `extra={"published": False}` for unpublished posts or
  `extra={"scheduled_publish_time": <unix>, "published": False}` to schedule.
- Photos/videos accept a fetchable `media_url`, a local `file_path`, or raw
  `content` bytes (multipart upload).

## Notes & limitations

- Personal **profiles** cannot be read — only Pages (Meta restricts profile
  data). Instagram accounts need the separate Instagram Graph API.
- Post insights need `read_insights`; without it the adapter still returns
  engagement (likes/comments/shares) and leaves impressions/reach as `None`.
- Insights metrics change between Graph versions; the provider pins v19.0.
