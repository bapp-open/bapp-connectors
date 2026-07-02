# Connecting Pinterest Ads

Creates and manages ad campaigns and reads performance via the
**Pinterest API v5**.

| | |
|---|---|
| Provider key | `ads` / `pinterest` |
| Auth | OAuth2 access token (Bearer) |
| Credentials | `token`, `ad_account_id`; `client_id` + `client_secret` for OAuth |
| Settings | — |
| Capabilities | `OAuthCapability` |

## What you get

- Campaigns / ad groups / ads: list, get, create, update, and status changes
  (`DELETED` maps to Pinterest's `ARCHIVED` — no hard delete)
- Targeting on the ad group: countries (`GEO`), age buckets (mapped from
  `age_min`/`age_max` to Pinterest's `18-24` … `65+` brackets), genders
- `get_insights()` at account / campaign / ad-group / ad level: impressions,
  clicks, spend, CTR, CPC, conversions

## Getting credentials

1. Create an app at [developers.pinterest.com](https://developers.pinterest.com/apps/)
   with a Pinterest **business** account that has an ad account.
2. Scopes the adapter uses: `ads:read`, `ads:write` (plus the pin scopes if you
   also use the social provider with the same token).
3. Run the OAuth flow — the adapter implements it (add `client_id` +
   `client_secret`; the token endpoint uses HTTP Basic auth, handled for you):
   `get_authorize_url` → `exchange_code_for_token` → `refresh_token()` when the
   ~30-day access token expires.
4. `ad_account_id` is shown in Pinterest Ads Manager (account switcher / URL).

## Quick start

```python
from decimal import Decimal
from bapp_connectors.core.dto.ads import (
    Ad, AdCampaign, AdCreative, AdGroup, AdInsightsLevel, AdObjective, AdTargeting,
)
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.ads.pinterest  # noqa: F401

ads = registry.create_adapter("ads", "pinterest",
                              credentials={"token": "pina_...", "ad_account_id": "549755885175"})

campaign = ads.create_campaign(AdCampaign(
    name="Spring lookbook", objective=AdObjective.TRAFFIC, daily_budget=Decimal("20"),
))
group = ads.create_ad_group(AdGroup(
    campaign_id=campaign.id, name="Women 25-44",
    daily_budget=Decimal("20"), bid_amount=Decimal("0.30"),
    targeting=AdTargeting(countries=["RO"], age_min=25, age_max=44, genders=["female"]),
))

# A Pinterest ad promotes an existing Pin — create one with the social/pinterest
# provider's publish_post, then reference its id:
ad = ads.create_ad(Ad(ad_group_id=group.id, name="Lookbook pin",
                      creative=AdCreative(id="8123456789012345678")))

for row in ads.get_insights(AdInsightsLevel.AD, entity_id=ad.id):
    print(row.impressions, row.clicks, row.spend, row.ctr)
```

## Notes & limitations

- **Budgets and bids are converted to Pinterest's micro-currency** (×1,000,000)
  automatically — the DTOs stay whole-currency `Decimal`s.
- **Ads promote existing Pins** — create the pin first (the `social/pinterest`
  provider's `publish_post` works) and pass its id as `creative.id`. There is
  no separate creative upload.
- Analytics accrue with ~24h delay; the default reporting window is the last
  30 days.
