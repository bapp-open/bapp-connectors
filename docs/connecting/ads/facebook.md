# Connecting Facebook Ads

Creates and manages campaigns, ad sets, and ads, and reads performance, via the
**Meta Marketing API v19.0**.

| | |
|---|---|
| Provider key | `ads` / `facebook` |
| Auth | Access token (Bearer) |
| Credentials | `token`, `ad_account_id` (numeric, without the `act_` prefix) |
| Settings | `default_optimization_goal` (default `LINK_CLICKS`), `default_billing_event` (default `IMPRESSIONS`), `page_id` (required for creative creation) |
| Capabilities | `CreativeUploadCapability` |

## What you get

- Campaigns / ad sets (`AdGroup`) / ads: list, get, create, update, and
  pause/resume/archive/delete via `set_*_status`
- Targeting on the ad set: countries, age range, genders; anything else
  (custom audiences, placements) passes through `targeting.extra`
- `get_insights()` at account / campaign / ad-set / ad level: impressions,
  clicks, spend, CTR, CPC/CPM, reach, frequency, conversions (purchase +
  offsite conversions), video views

## Getting credentials

1. Create a **Business**-type app at
   [developers.facebook.com](https://developers.facebook.com/apps/) and add the
   **Marketing API** product.
2. Recommended for servers: create a **System User** in
   [Business Manager](https://business.facebook.com/settings/system-users),
   assign it to the ad account with *Manage campaigns* access, and generate a
   token with scopes `ads_management`, `ads_read`, `business_management`.
   (Alternative: Facebook Login with the same scopes → long-lived user token.)
3. Find your **ad account ID** in Ads Manager (Account overview) or Business
   settings — use the numeric part only; the adapter adds the `act_` prefix.
4. New apps start in *development* mode: only ad accounts owned by app
   admins/developers work until App Review approves `ads_management` — plan the
   review before production.

## Quick start

```python
from decimal import Decimal
from bapp_connectors.core.dto.ads import (
    Ad, AdCampaign, AdCreative, AdEntityStatus, AdGroup, AdInsightsLevel, AdObjective, AdTargeting,
)
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.ads.facebook  # noqa: F401

ads = registry.create_adapter("ads", "facebook",
                              credentials={"token": "EAAB...", "ad_account_id": "1234567890"})

campaign = ads.create_campaign(AdCampaign(
    name="Summer sale", objective=AdObjective.SALES, daily_budget=Decimal("50"),
))
ad_set = ads.create_ad_group(AdGroup(
    campaign_id=campaign.id, name="RO 18-35", daily_budget=Decimal("25"),
    targeting=AdTargeting(countries=["RO"], age_min=18, age_max=35),
))
ad = ads.create_ad(Ad(
    ad_group_id=ad_set.id, name="Hero ad",
    creative=AdCreative(id="120210123456789"),  # existing creative ID
))

ads.set_campaign_status(campaign.id, AdEntityStatus.ACTIVE)

for row in ads.get_insights(AdInsightsLevel.AD):
    print(row.entity_id, row.impressions, row.clicks, row.spend, row.conversions)
```

## Uploading media & creating creatives

Set the `page_id` setting (ads publish on behalf of a Page), then:

```python
from bapp_connectors.core.dto.ads import AdCreative, AdMediaAsset, AdMediaType

media = ads.upload_media(AdMediaAsset(media_type=AdMediaType.VIDEO,
                                      url="https://cdn.example.com/promo.mp4"))
creative = ads.create_creative(
    AdCreative(title="Summer sale", body="Up to 40% off", landing_url="https://example.com",
               call_to_action="SHOP_NOW"),
    media=media,
)
ads.create_ad(Ad(ad_group_id=ad_set.id, name="Promo video", creative=creative))
```

- **Images** upload from `file_path`/`content` (multipart to `adimages`; Meta
  can't fetch image URLs) and become an `image_hash` used in link ads.
- **Videos** upload from a fetchable `url` (`file_url`) or `file_path`/`content`.
- The token needs `pages_read_engagement` (and the app advertiser access to
  the Page) for `object_story_spec` creatives.

## Notes & limitations

- **Budgets** are sent to Meta in minor units (cents) automatically — the DTOs
  use whole-currency `Decimal`s. Campaigns are created `PAUSED` by default;
  activate explicitly.
- **Creatives:** use `upload_media` + `create_creative` (above), pass an
  existing `creative.id`, or a raw `object_story_spec` via
  `ad.extra["object_story_spec"]`.
- New campaigns must declare `special_ad_categories`; the adapter sends `[]`
  (none) — housing/credit/employment/politics advertisers must set the correct
  category via the update payload.
- Rate limiting: the Marketing API throttles per ad account; the adapter
  retries on Meta's rate-limit error codes (4, 17, 32, 613, 8000x).
