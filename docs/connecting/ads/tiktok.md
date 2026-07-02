# Connecting TikTok Ads

Creates and manages campaigns, ad groups, and ads, and reads performance, via
the **TikTok Business API v1.3**.

| | |
|---|---|
| Provider key | `ads` / `tiktok` |
| Auth | Long-term access token (`Access-Token` header) |
| Credentials | `access_token`, `advertiser_id` |
| Settings | — |
| Capabilities | `CreativeUploadCapability` |

## What you get

- Campaigns / ad groups / ads: list, get, create, update, and
  enable/disable/delete via `set_*_status`
- Targeting on the ad group: age brackets (mapped from `age_min`/`age_max` to
  TikTok's `AGE_18_24`-style buckets), gender; locations via numeric TikTok
  `location_ids` in `targeting.extra`
- `get_insights()` at advertiser / campaign / ad-group / ad level from the
  integrated report: spend, impressions, clicks, CTR, CPC/CPM, reach,
  frequency, conversions, video plays — one row per day

## Getting credentials

1. Create a developer app at
   [business-api.tiktok.com](https://business-api.tiktok.com/portal) (TikTok
   for Business → My Apps). Request the **Ads Management** and **Reporting**
   scopes.
2. Have the advertiser authorize the app: open the app's *Advertiser
   authorization URL*, log in with the TikTok for Business account that owns
   the ad account, and approve.
3. Exchange the returned `auth_code` at `/open_api/v1.3/oauth2/access_token/`
   for a **long-term access token** (does not expire; invalidated when the
   authorization is revoked).
4. Find the **advertiser ID** in TikTok Ads Manager (top-left account switcher)
   or from the token exchange response's `advertiser_ids` list.

## Quick start

```python
from decimal import Decimal
from bapp_connectors.core.dto.ads import (
    Ad, AdCampaign, AdCreative, AdEntityStatus, AdGroup, AdInsightsLevel, AdObjective, AdTargeting,
)
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.ads.tiktok  # noqa: F401

ads = registry.create_adapter("ads", "tiktok",
                              credentials={"access_token": "...", "advertiser_id": "6900000000000000000"})

campaign = ads.create_campaign(AdCampaign(
    name="App installs Q3", objective=AdObjective.TRAFFIC, daily_budget=Decimal("100"),
))
group = ads.create_ad_group(AdGroup(
    campaign_id=campaign.id, name="18-34 video", daily_budget=Decimal("50"),
    targeting=AdTargeting(age_min=18, age_max=34, genders=["female"],
                          extra={"location_ids": ["6252001"]}),  # TikTok numeric geo IDs
))
ad = ads.create_ad(Ad(
    ad_group_id=group.id, name="Spark ad #1",
    creative=AdCreative(body="Shop the drop", landing_url="https://example.com",
                        call_to_action="SHOP_NOW"),
    extra={"video_id": "v10033g50000..."},  # pre-uploaded video
))

for row in ads.get_insights(AdInsightsLevel.AD, entity_id=ad.id):
    print(row.date_start, row.impressions, row.clicks, row.spend)
```

## Uploading media

```python
from bapp_connectors.core.dto.ads import AdCreative, AdMediaAsset, AdMediaType

media = ads.upload_media(AdMediaAsset(media_type=AdMediaType.VIDEO,
                                      file_path="/videos/promo.mp4"))   # or url=
creative = ads.create_creative(
    AdCreative(body="Shop the drop", landing_url="https://example.com",
               call_to_action="SHOP_NOW"),
    media=media,
)
ads.create_ad(Ad(ad_group_id=group.id, name="Promo", creative=creative))
```

- Images and videos upload **by URL or by file/bytes** (file uploads send the
  MD5 signature TikTok requires automatically).
- TikTok creatives are **inline to the ad** — `create_creative` returns the
  creative with `video_id`/`image_ids` merged into `extra`, which
  `create_ad` consumes; there is no standalone creative id.

## Notes & limitations

- **Budgets** are whole-currency `Decimal`s; the adapter picks the TikTok
  budget mode (`BUDGET_MODE_DAY` / `BUDGET_MODE_TOTAL` / `BUDGET_MODE_INFINITE`)
  from which budget field is set. TikTok enforces minimum budgets (typically
  50/day campaign, 20/day ad group in account currency).
- **Geo targeting** uses TikTok numeric location IDs, not ISO codes — fetch
  them from TikTok's `tool/region/` endpoint upstream and pass
  `targeting.extra["location_ids"]`.
- **Creatives** come from `upload_media` + `create_creative` (above) or
  pre-uploaded assets (`video_id`, `image_ids` in `ad.extra`). Spark Ads
  (`identity_id`/`identity_type`) pass through `ad.extra`.
- Insights default to the **last 7 days** when no period is given, one row per
  day per entity.
