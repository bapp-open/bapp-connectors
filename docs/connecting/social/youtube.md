# Connecting YouTube Shorts (social)

Reads a channel's profile, uploads, and video stats via the **YouTube Data API v3**,
with built-in filtering to Shorts-length videos.

| | |
|---|---|
| Provider key | `social` / `youtube` |
| Auth | API key **or** OAuth2 access token |
| Credentials | `api_key` (optional), `access_token` (optional — at least one required) |
| Settings | `channel_id`, `shorts_only` (default `true`), `shorts_max_seconds` (default `180`) |
| Capabilities | `SocialPublishCapability` |

## What you get

- `get_account()` — channel: handle, title, avatar, subscriber/video counts
- `list_posts()` / `get_post()` — uploads, filtered to Shorts when `shorts_only`
  (duration ≤ `shorts_max_seconds`; videos above the threshold map as `VIDEO`, at or below as `SHORT_VIDEO`)
- `get_post_stats()` — views, likes, comments (shares are not exposed by the Data API → `None`)
- `get_account_stats()` — subscribers, video count, lifetime channel views

## Getting credentials

### Option A — API key (public data, simplest)

1. In the [Google Cloud Console](https://console.cloud.google.com/), create a
   project and enable **YouTube Data API v3** (APIs & Services → Library).
2. Create an **API key** (APIs & Services → Credentials) and restrict it to the
   YouTube Data API.
3. Use it as the `api_key` credential, and set the `channel_id` setting to the
   channel you want to read (the `UC...` ID — visible in the channel URL or via
   YouTube Studio → Settings → Channel → Advanced).

### Option B — OAuth2 (act as the channel owner)

1. Same project/API enablement as above; configure the OAuth consent screen.
2. Create OAuth client credentials and run the flow with scope
   `https://www.googleapis.com/auth/youtube.readonly` — add
   `https://www.googleapis.com/auth/youtube.upload` if you will publish videos
   with `publish_post`.
3. Use the resulting access token as the `access_token` credential. When set,
   `channel_id` may be omitted — the authorized user's own channel is used.

> **Token lifetime:** OAuth access tokens expire after ~1 hour; refresh them
> outside the adapter. API keys do not expire but only read public data.

## Quick start

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.youtube  # noqa: F401

adapter = registry.create_adapter(
    "social", "youtube",
    credentials={"api_key": "AIza..."},
    config={"channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx", "shorts_only": "true"},
)

for short in adapter.list_posts(limit=25).items:
    print(short.title, short.duration_seconds, short.stats.views)
```

## Publishing (uploading videos)

```python
from bapp_connectors.core.dto.social import SocialPostDraft, SocialPrivacy

result = adapter.publish_post(SocialPostDraft(
    title="Behind the scenes", description="#shorts",
    file_path="/videos/clip.mp4",             # or content=<bytes>
    privacy=SocialPrivacy.UNLISTED,           # public / private / unlisted
))
print(result.post_id, result.url)             # id is available immediately
status = adapter.check_publish_status(result.post_id)  # processing → published
```

- Requires the **`access_token`** credential with the `youtube.upload` scope —
  API keys cannot publish.
- Upload needs the bytes (`file_path` or `content`); `media_url` is rejected —
  YouTube does not pull from URLs.
- There is no separate Shorts endpoint: a video **≤ 3 minutes with a vertical
  or square aspect ratio** becomes a Short automatically.
- `extra` passes through `category_id` and `made_for_kids`.
- Quota: an upload costs ~1,600 Data API units (of the default 10,000/day).

## Notes & limitations

- Every call costs Data API **quota units** (default 10,000/day per project);
  `list_posts` uses playlistItems + videos lookups, which are cheap (1 unit each).
- YouTube has no explicit "is a Short" flag in the Data API — the duration
  threshold (`shorts_max_seconds`, default 180s to match the current Shorts
  limit) is the standard heuristic. Set `shorts_only` to `false` to include all
  uploads.
- Impressions/CTR/watch time require the **YouTube Analytics API** (channel
  owner OAuth only), which is not covered by this provider; those fields are
  `None`.
