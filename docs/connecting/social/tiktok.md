# Connecting TikTok (social)

Reads a TikTok user's profile, videos, and stats via the **TikTok Display API v2**.

| | |
|---|---|
| Provider key | `social` / `tiktok` |
| Auth | OAuth2 user access token (Bearer) |
| Credentials | `token` |
| Settings | — |

## What you get

- `get_account()` — profile: username, display name, avatar, bio, follower/following/video counts
- `list_posts()` / `get_post()` — the user's videos (mapped as `SHORT_VIDEO`)
- `get_post_stats()` — views, likes, comments, shares (saves/impressions/reach are not exposed by the Display API → `None`)
- `get_account_stats()` — followers, following, video count, total likes

## Getting credentials

1. Register at the [TikTok for Developers portal](https://developers.tiktok.com/) and create an app.
2. Add the **Login Kit** product to the app and request these scopes:
   - `user.info.basic` — open_id, avatar, display name
   - `user.info.profile` — username, bio, verified flag, profile link
   - `user.info.stats` — follower/following/likes/video counts
   - `video.list` — the user's public videos
3. Submit the app for review (required before non-sandbox users can authorize).
4. Run the OAuth authorization-code flow against `https://www.tiktok.com/v2/auth/authorize/`;
   exchange the code at `https://open.tiktokapis.com/v2/oauth/token/` for an access token.
5. Use the resulting **access token** as the `token` credential.

> **Token lifetime:** TikTok user access tokens expire after ~24 hours and come
> with a refresh token (valid ~1 year). Refresh outside the adapter and update
> the stored credential — the adapter expects a currently-valid token.

## Quick start

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.tiktok  # noqa: F401

adapter = registry.create_adapter("social", "tiktok", credentials={"token": "act.example..."})

print(adapter.test_connection())

page = adapter.list_posts(limit=20)
for video in page.items:
    print(video.title, video.url, video.stats.views, video.stats.likes)

if page.has_more:
    next_page = adapter.list_posts(limit=20, cursor=page.cursor)
```

## Notes & limitations

- The Display API only returns **public videos of the authorizing user** — you
  cannot read arbitrary accounts.
- Stats are lifetime counters; TikTok exposes no period-scoped account metrics
  here, so `get_account_stats(since, until)` returns lifetime values with the
  period echoed back.
- Deeper analytics (watch time, traffic sources) require TikTok's Research or
  Business APIs, which need separate approval and are not covered by this
  provider.
