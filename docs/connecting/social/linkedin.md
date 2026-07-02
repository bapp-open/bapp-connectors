# Connecting LinkedIn Page (social)

Reads a LinkedIn **organization (company) page**'s profile, posts, and share
statistics, and publishes text/article posts, via the LinkedIn
Marketing/Community Management REST APIs.

| | |
|---|---|
| Provider key | `social` / `linkedin` |
| Auth | OAuth2 access token (Bearer + Rest.li headers) |
| Credentials | `access_token`, `organization_id`; `client_id` + `client_secret` for OAuth |
| Settings | `linkedin_version` (default `202405`) |
| Capabilities | `SocialPublishCapability`, `OAuthCapability` |

## What you get

- `get_account()` — organization name, vanity URL, description, follower count
- `list_posts()` / `get_post()` — page posts (offset-based pagination)
- `get_post_stats()` — impressions, likes, comments, shares, clicks, engagement rate from share statistics
- `get_account_stats()` — followers + lifetime aggregate share statistics
- `publish_post()` — text and article-link posts

## Getting credentials

1. Create an app at the
   [LinkedIn Developer Portal](https://developer.linkedin.com/) and associate
   it with your company page (the page admin must verify the app).
2. Request access to the **Community Management API** (and/or Marketing
   Developer Platform) — this grants the scopes the adapter uses:
   `r_organization_social`, `w_organization_social`, `rw_organization_admin`.
3. Run the OAuth flow — the adapter implements it (add `client_id` +
   `client_secret`): `get_authorize_url` → user (a page admin) approves →
   `exchange_code_for_token`. Access tokens last ~60 days; approved Marketing
   partners also receive a **refresh token** (~1 year) usable with
   `refresh_token()` — the adapter tolerates its absence.
4. `organization_id` is the numeric ID in the page's admin URL
   (`linkedin.com/company/<id>/admin/`).

## Quick start

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.linkedin  # noqa: F401

adapter = registry.create_adapter(
    "social", "linkedin",
    credentials={"access_token": "AQV...", "organization_id": "12345678"},
)

for post in adapter.list_posts(limit=10).items:
    stats = adapter.get_post_stats(post.id)  # id is a URN like "urn:li:share:7123..."
    print(post.description[:50], stats.impressions, stats.likes, stats.clicks)
```

## Publishing

```python
from bapp_connectors.core.dto.social import SocialPostDraft

# Text post
adapter.publish_post(SocialPostDraft(description="We're hiring!"))

# Article / link post
adapter.publish_post(SocialPostDraft(description="Our Q2 results are out.",
                                     link="https://example.com/blog/q2",
                                     title="Q2 Results"))
```

- Posts publish as the **organization**, publicly, to the main feed.
- Image/video posts require LinkedIn's `initializeUpload` asset flow, which is
  not wrapped yet — media drafts raise `ValidationError`.

## Notes & limitations

- The `LinkedIn-Version` header is date-pinned (`linkedin_version` setting);
  LinkedIn sunsets old versions roughly yearly — bump the setting when needed.
- Video view counts are not part of share statistics — `stats.views` is `None`.
- Community Management API access requires LinkedIn's app review; development
  tier works with your own page.
