# Connecting Social & Ads Providers

Step-by-step connection guides for the `social` and `ads` provider families:

| Family | Provider | Guide |
|--------|----------|-------|
| social | TikTok | [social/tiktok.md](social/tiktok.md) |
| social | YouTube Shorts | [social/youtube.md](social/youtube.md) |
| social | Facebook Page | [social/facebook.md](social/facebook.md) |
| ads | Facebook Ads | [ads/facebook.md](ads/facebook.md) |
| ads | TikTok Ads | [ads/tiktok.md](ads/tiktok.md) |
| ads | Google Ads | [ads/google.md](ads/google.md) |

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

### Known gaps (not yet implemented)

- **Creative/media upload** — adapters reference existing creatives (Meta
  creative IDs, TikTok `video_id`/`image_ids`, Google responsive search ad
  text). Uploading images/videos to the platforms' asset libraries is not
  covered yet.
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
- **OAuth token refresh** — adapters expect a valid access token; refreshing
  (Google, TikTok, Meta long-lived exchange) happens outside the adapter.
