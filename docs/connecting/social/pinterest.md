# Connecting Pinterest (social)

Reads a Pinterest account's profile, pins, and analytics, and creates image
pins, via the **Pinterest API v5**.

| | |
|---|---|
| Provider key | `social` / `pinterest` |
| Auth | OAuth2 access token (Bearer) |
| Credentials | `token`; `client_id` + `client_secret` for OAuth |
| Settings | `default_board_id` (board used by `publish_post` when the draft doesn't specify one) |
| Capabilities | `SocialPublishCapability`, `OAuthCapability` |

## What you get

- `get_account()` — username, avatar, follower/following counts (monthly views in `extra`)
- `list_posts()` / `get_post()` — pins (bookmark-based pagination)
- `get_post_stats()` — impressions, saves, clicks (pin + outbound) over the last 90 days;
  likes/comments/views are `None` — Pinterest doesn't expose them here
- `get_account_stats(since, until)` — account impressions over the period + followers
- `publish_post()` — image pins by URL onto a board

## Getting credentials

1. Create an app at
   [developers.pinterest.com](https://developers.pinterest.com/apps/) (a
   business account is required; trial access works with your own account).
2. Scopes the adapter uses: `user_accounts:read`, `boards:read`, `pins:read`,
   `pins:write`.
3. Run the OAuth flow — the adapter implements it (add `client_id` +
   `client_secret`): `get_authorize_url` → `exchange_code_for_token` (token
   endpoint uses HTTP Basic auth with your client credentials — handled by the
   adapter). Access tokens last ~30 days, refresh tokens ~1 year; refresh with
   `refresh_token()`.

## Quick start

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.pinterest  # noqa: F401

adapter = registry.create_adapter(
    "social", "pinterest",
    credentials={"token": "pina_..."},
    config={"default_board_id": "1234567890"},
)

for pin in adapter.list_posts(limit=25).items:
    stats = adapter.get_post_stats(pin.id)
    print(pin.title, stats.impressions, stats.saves, stats.clicks)
```

## Publishing

```python
from bapp_connectors.core.dto.social import SocialMediaType, SocialPostDraft

adapter.publish_post(SocialPostDraft(
    title="Summer lookbook", description="Our new collection",
    media_type=SocialMediaType.IMAGE,
    media_url="https://cdn.example.com/look.jpg",
    link="https://example.com/collection",           # click-through destination
    extra={"board_id": "1234567890"},                # or rely on default_board_id
))
```

- Pins require a **board** — from `draft.extra["board_id"]` or the
  `default_board_id` setting.
- Image pins by URL only; video pins need Pinterest's async media upload API
  (not wrapped yet), and text-only posts don't exist on Pinterest.

## Notes & limitations

- Pin analytics need the account to own the pins; metrics accrue with delay
  (~24h).
- For advertising, see the separate [Pinterest Ads guide](../ads/pinterest.md).
