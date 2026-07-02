# Connecting LinkedIn Ads

Creates and manages sponsored campaigns and reads performance via the
**LinkedIn Marketing API** (api.linkedin.com/rest).

| | |
|---|---|
| Provider key | `ads` / `linkedin` |
| Auth | OAuth2 access token (Bearer + Rest.li headers) |
| Credentials | `access_token`, `ad_account_id`; `client_id` + `client_secret` for OAuth |
| Settings | `linkedin_version` (default `202405`) |
| Capabilities | `OAuthCapability` |

## Hierarchy mapping — read this first

LinkedIn's structure differs from Meta/TikTok/Google, so the normalized
hierarchy maps like this:

| Framework | LinkedIn |
|-----------|----------|
| `AdCampaign` | **Campaign Group** (budget/schedule container) |
| `AdGroup` | **Campaign** (targeting, budget, bidding) |
| `Ad` | **Creative** (references an organic post) |

## What you get

- Campaign groups / campaigns / creatives: list, get, create, update,
  status changes (`DELETED` maps to LinkedIn's `ARCHIVED` — no hard delete)
- Targeting on the `AdGroup` level: LinkedIn geo URNs via
  `targeting.extra["geo_urns"]` (LinkedIn doesn't use ISO country codes)
- `get_insights()` at account / campaign-group / campaign / creative level:
  impressions, clicks, spend, conversions; CTR/CPC/CPM derived

## Getting credentials

1. Create an app at the [LinkedIn Developer Portal](https://developer.linkedin.com/)
   and apply for the **Advertising API** (Marketing Developer Platform) — this
   is a reviewed program.
2. Scopes the adapter uses: `rw_ads`, `r_ads_reporting`.
3. Run the OAuth flow — the adapter implements it (add `client_id` +
   `client_secret`): `get_authorize_url` → `exchange_code_for_token`;
   `refresh_token()` works for approved partners (refresh tokens ~1 year; the
   adapter tolerates their absence).
4. `ad_account_id` is the numeric sponsored account ID from Campaign Manager's
   URL or account settings.

## Quick start

```python
from decimal import Decimal
from bapp_connectors.core.dto.ads import Ad, AdCampaign, AdCreative, AdGroup, AdInsightsLevel
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.ads.linkedin  # noqa: F401

ads = registry.create_adapter("ads", "linkedin",
                              credentials={"access_token": "AQV...", "ad_account_id": "512345678"})

group = ads.create_campaign(AdCampaign(name="Q3 lead gen", lifetime_budget=Decimal("1000")))
campaign = ads.create_ad_group(AdGroup(
    campaign_id=group.id, name="DACH IT decision makers",
    daily_budget=Decimal("50"), bid_amount=Decimal("4"),
))

# A LinkedIn creative promotes an organic post — publish one first
# (e.g. with the social/linkedin provider), then reference its URN:
ad = ads.create_ad(Ad(ad_group_id=campaign.id, name="Sponsored post",
                      creative=AdCreative(id="urn:li:share:7123456789")))

for row in ads.get_insights(AdInsightsLevel.AD_GROUP, entity_id=campaign.id):
    print(row.impressions, row.clicks, row.spend, row.conversions)
```

## Notes & limitations

- **Creatives reference organic posts** — create the post via the
  `social/linkedin` provider's `publish_post` and pass its URN as
  `creative.id` (or `ad.extra["content_reference"]`). There is no standalone
  media upload here.
- Targeting beyond geo (job titles, industries, audiences) passes through
  `targeting.extra` as raw LinkedIn facet URNs.
- The `LinkedIn-Version` header is date-pinned — bump the `linkedin_version`
  setting when LinkedIn sunsets a version.
