# Connecting Social & Ads Providers

Step-by-step connection guides for the `social` and `ads` provider families:

| Family | Provider | Guide |
|--------|----------|-------|
| social | TikTok | [social/tiktok.md](social/tiktok.md) |
| social | YouTube Shorts | [social/youtube.md](social/youtube.md) |
| social | Facebook Page | [social/facebook.md](social/facebook.md) |
| social | Instagram | [social/instagram.md](social/instagram.md) |
| social | Threads | [social/threads.md](social/threads.md) |
| social | LinkedIn Page | [social/linkedin.md](social/linkedin.md) |
| social | Pinterest | [social/pinterest.md](social/pinterest.md) |
| ads | Facebook Ads | [ads/facebook.md](ads/facebook.md) |
| ads | TikTok Ads | [ads/tiktok.md](ads/tiktok.md) |
| ads | Google Ads | [ads/google.md](ads/google.md) |
| ads | Microsoft Ads | [ads/microsoft.md](ads/microsoft.md) |
| ads | LinkedIn Ads | [ads/linkedin.md](ads/linkedin.md) |
| ads | Pinterest Ads | [ads/pinterest.md](ads/pinterest.md) |

Note: Instagram *advertising* runs through `ads/facebook` (Meta placements),
and YouTube *advertising* through `ads/google` (VIDEO campaigns) — no separate
providers needed. LinkedIn Ads and Pinterest Ads promote organic posts/pins
created via their social siblings.

## The universal stats interface (social)

Every social provider returns the same DTOs regardless of platform, so metrics
can be aggregated across TikTok, YouTube, and Facebook with one code path:

```python
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.social.tiktok    # noqa: F401 — triggers registration
import bapp_connectors.providers.social.youtube   # noqa: F401
import bapp_connectors.providers.social.facebook  # noqa: F401

connections = [
    ("tiktok", {"token": "act.abc..."}, {}),
    ("youtube", {"api_key": "AIza..."}, {"channel_id": "UC..."}),
    ("facebook", {"token": "EAAB...", "page_id": "1234567890"}, {}),
]

for provider, credentials, config in connections:
    adapter = registry.create_adapter("social", provider, credentials, config=config)
    for post in adapter.list_posts(limit=10).items:
        stats = post.stats or adapter.get_post_stats(post.id)
        print(provider, post.title or post.description[:40], stats.views, stats.likes)
```

Rules of the interface:

- A metric the platform does not expose is `None`, never `0`. `0` always means
  "measured as zero".
- Platform-specific metrics that have no universal equivalent are preserved in
  `stats.extra`.
- `SocialPostStats.engagements` sums whichever of likes/comments/shares/saves
  the platform exposes.

## The ads model

The three ads platforms are normalized onto one hierarchy:

```
AdCampaign  →  AdGroup  →  Ad
               (Meta "ad set" / TikTok "adgroup" / Google "ad group")
```

### Where does targeting live?

**On the ad group** — because that is where all three platforms attach it. An
individual ad cannot carry its own audience. To serve different targeting to
different ads, create one ad group per audience and place the ads inside:

```python
from decimal import Decimal
from bapp_connectors.core.dto.ads import Ad, AdCampaign, AdCreative, AdGroup, AdObjective, AdTargeting

ads = registry.create_adapter("ads", "facebook", {"token": "...", "ad_account_id": "1234567890"})

campaign = ads.create_campaign(AdCampaign(name="Summer sale", objective=AdObjective.SALES, daily_budget=Decimal("50")))

young = ads.create_ad_group(AdGroup(
    campaign_id=campaign.id, name="18-24 RO", daily_budget=Decimal("25"),
    targeting=AdTargeting(countries=["RO"], age_min=18, age_max=24),
))
older = ads.create_ad_group(AdGroup(
    campaign_id=campaign.id, name="25-45 RO+HU", daily_budget=Decimal("25"),
    targeting=AdTargeting(countries=["RO", "HU"], age_min=25, age_max=45),
))

for group in (young, older):
    ads.create_ad(Ad(ad_group_id=group.id, name=f"Hero video — {group.name}",
                     creative=AdCreative(id="creative-id-or-see-provider-guide")))
```

`AdTargeting` covers countries, age range, genders, interests, and languages;
anything platform-specific passes through `targeting.extra` untouched (e.g.
TikTok numeric `location_ids`, Meta `custom_audiences`).

### Seeing ad performance

`get_insights()` is the universal reporting interface, at any level of the
hierarchy — including per-ad:

```python
from datetime import datetime, timedelta
from bapp_connectors.core.dto.ads import AdInsightsLevel

since = datetime.now() - timedelta(days=7)

# One row per ad — impressions, clicks, spend, CTR, CPC/CPM, conversions
for row in ads.get_insights(AdInsightsLevel.AD, since=since, until=datetime.now()):
    print(row.entity_id, row.impressions, row.clicks, row.spend, row.ctr, row.conversions)

# Or a single campaign / ad group / the whole account
ads.get_insights(AdInsightsLevel.CAMPAIGN, entity_id=campaign.id)
ads.get_insights(AdInsightsLevel.ACCOUNT)
```

Same `None`-means-unavailable rule as social stats. TikTok returns one row per
day (`stat_time_day`); Meta and Google aggregate over the requested range
unless the platform segments it.

### Uploading media and creating creatives

Ads providers implement `CreativeUploadCapability` — from a media file to a
running ad in one flow:

```python
from bapp_connectors.core.capabilities import CreativeUploadCapability
from bapp_connectors.core.dto.ads import Ad, AdCreative, AdMediaAsset, AdMediaType

assert ads.supports(CreativeUploadCapability)

media = ads.upload_media(AdMediaAsset(media_type=AdMediaType.VIDEO, url="https://cdn.example.com/promo.mp4"))
creative = ads.create_creative(
    AdCreative(title="Summer sale", body="Up to 40% off", landing_url="https://example.com",
               call_to_action="SHOP_NOW"),
    media=media,
)
ads.create_ad(Ad(ad_group_id=group.id, name="Promo video", creative=creative))
```

Platform boundaries (raised as clear errors, see each guide):

- **Meta** — images upload from file/bytes, videos from file/bytes or URL;
  `create_creative` needs the `page_id` setting (creatives publish as a Page).
- **TikTok** — images and videos upload by URL or file; creatives are inline
  to the ad, so `create_creative` returns the creative with the media
  reference merged into `extra` for `create_ad` to consume.
- **Google** — image assets upload from file/bytes; video is not hosted by
  Google Ads (upload to YouTube — e.g. via the social/youtube provider — and
  reference the video id), and search-ad creatives are inline text, so
  `create_creative` raises `UnsupportedFeatureError`.

## Publishing to social platforms

Social providers implement `SocialPublishCapability` — the write counterpart
of the universal stats interface:

```python
from bapp_connectors.core.capabilities import SocialPublishCapability
from bapp_connectors.core.dto.social import PublishStatus, SocialPostDraft

result = adapter.publish_post(SocialPostDraft(
    title="New drop", description="Behind the scenes #shorts",
    media_url="https://cdn.example.com/clip.mp4",  # or file_path= / content=
))
while result.status == PublishStatus.PROCESSING:
    result = adapter.check_publish_status(result.publish_id or result.post_id)
print(result.post_id, result.url)
```

Platform boundaries:

- **TikTok** — direct post pulls the video from a public URL you host
  (`media_url`); publishing is async (poll `check_publish_status`). Needs the
  `video.publish` scope.
- **YouTube** — resumable upload from `file_path`/`content` (OAuth
  `youtube.upload` scope required; API keys cannot publish). Videos ≤ 3
  minutes with vertical/square aspect become Shorts automatically.
- **Facebook Page** — text/link posts, photos (URL or file), and videos (URL
  or file); videos are async while Meta transcodes. Needs `pages_manage_posts`.

## OAuth flows & token refresh

Every provider in these two families implements `OAuthCapability`, so the full
token lifecycle — authorize, exchange, refresh — runs through the adapter:

```python
from bapp_connectors.core.capabilities import OAuthCapability

# 1. Build an adapter with just the app credentials (no user token yet)
adapter = registry.create_adapter("social", "youtube",
                                  credentials={"client_id": "...", "client_secret": "..."})
assert adapter.supports(OAuthCapability)

# 2. Send the user to authorize, then exchange the callback code
url = adapter.get_authorize_url("https://myapp.example/callback", state="xyz")
tokens = adapter.exchange_code_for_token(code, "https://myapp.example/callback")

# 3. tokens.extra["credentials"] is ready to merge into the stored Connection
#    credentials — keys already match the provider's credential field names.

# 4. When the access token expires, refresh it
fresh = adapter.refresh_token(tokens.refresh_token)
```

Platform lifecycles differ — the adapters encode them honestly:

| Platform | Access token | Refresh |
|----------|--------------|---------|
| Google (YouTube, Google Ads) | ~1 hour | standard `refresh_token` grant |
| TikTok Login Kit (social) | ~24 hours | refresh grant; the refresh token **rotates** — store the returned one |
| Meta (Facebook social + ads) | ~60 days long-lived | no refresh tokens: `refresh_token(current_token)` runs the `fb_exchange_token` long-lived exchange |
| TikTok for Business (ads) | long-term | no refresh endpoint — `refresh_token` raises `UnsupportedFeatureError`; re-run the flow to rotate |

### Account pickers — finishing the connection

After the OAuth redirect, most platforms still need to know *which* account
the connection targets. Every provider that needs an extra ID has a discovery
helper (or surfaces it in the token exchange), so the whole initial connection
can be: authorize → pick from a list → done.

| Provider | Helper | Store as |
|----------|--------|----------|
| social/facebook | `list_page_tokens(user_token)` | `token` (page token) + `page_id` |
| social/instagram | `list_instagram_accounts(user_token)` | `token` (page token) + `ig_user_id` |
| social/linkedin | `list_organizations()` | `organization_id` |
| social/threads | user id in `tokens.extra` | — (token is enough) |
| ads/facebook | `list_ad_accounts(user_token)` | `ad_account_id` |
| ads/tiktok | `advertiser_ids` in `tokens.extra` | `advertiser_id` |
| ads/google | `list_accessible_customers()` | `customer_id` |
| ads/linkedin | `list_ad_accounts()` | `ad_account_id` |
| ads/pinterest | `list_ad_accounts()` | `ad_account_id` |

TikTok (social), YouTube, and Pinterest (social) need no picker — the token
alone identifies the account. Two things stay manual: Google/Microsoft
`developer_token`s (one-time per organization; platform policy, not
replaceable by OAuth), and Microsoft's `customer_id`/`account_id` (the Bing
Customer Management service isn't wrapped — read them from the Microsoft
Advertising UI).

### Known gaps (not yet implemented)

- **Custom / lookalike audiences & retargeting** — pass platform audience IDs
  through `targeting.extra`; there is no API for creating audiences.
- **Placements, dayparting, bidding strategies** — platform defaults are used;
  overrides go through `extra`.
- **A/B experiments** — no wrapper for the platforms' split-testing APIs
  (multiple ad groups with different targeting is the manual equivalent).
- **Google budget updates** — a Google campaign budget is a separate resource;
  `update_campaign` rejects `daily_budget` changes (create-time budgets work).
- **Google ad edits** — Google ads are immutable by design; only status changes
  are allowed (create a new ad to change content).
- **TikTok geo resolution** — TikTok targets numeric location IDs, not ISO
  country codes; resolve them upstream and pass via `targeting.extra["location_ids"]`.
