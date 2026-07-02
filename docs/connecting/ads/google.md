# Connecting Google Ads

Creates and manages campaigns, ad groups, and ads, and reads performance, via
the **Google Ads REST API v17** (GAQL).

| | |
|---|---|
| Provider key | `ads` / `google` |
| Auth | OAuth2 access token + developer token (headers) |
| Credentials | `developer_token`, `access_token`, `customer_id`, `login_customer_id` (optional) |
| Settings | `currency` (default `USD`, fallback label for spend) |
| Capabilities | `CreativeUploadCapability` (image assets only — see below), `OAuthCapability` |

## What you get

- Campaigns / ad groups / ads: list, get, create, update; pause/resume via
  `set_*_status`, delete via Google *remove* operations
- Campaign creation handles Google's two-step flow automatically (campaign
  budget resource + campaign, Manual CPC)
- Ad creation builds a **responsive search ad** from
  `AdCreative(title, body, landing_url)`
- `get_insights()` at account / campaign / ad-group / ad level: impressions,
  clicks, cost, CTR, average CPC/CPM, conversions, conversion value, video views

## Getting credentials

1. **Developer token** — in a Google Ads **Manager (MCC) account**, go to
   Tools & Settings → Setup → API Center and apply for a token. New tokens
   start with *test account only* access; apply for Basic access for
   production.
2. **OAuth2** — in the [Google Cloud Console](https://console.cloud.google.com/),
   enable the **Google Ads API**, configure the consent screen, create an OAuth
   client, and run the flow with scope `https://www.googleapis.com/auth/adwords`
   for a user with access to the ads account. Use the resulting access token as
   `access_token` — it expires after ~1 hour; the adapter implements the full
   flow (`get_authorize_url` / `exchange_code_for_token` / `refresh_token`,
   add the `client_id` + `client_secret` credentials). See the
   [overview](../README.md#oauth-flows--token-refresh).
3. **customer_id** — the 10-digit ID of the ads account to operate on (dashes
   are stripped automatically, `123-456-7890` is fine).
4. **login_customer_id** — set to the manager account's ID when the OAuth user
   accesses the account *through* an MCC; omit for direct account access.

## Quick start

```python
from decimal import Decimal
from bapp_connectors.core.dto.ads import (
    Ad, AdCampaign, AdCreative, AdEntityStatus, AdGroup, AdInsightsLevel, AdObjective,
)
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.ads.google  # noqa: F401

ads = registry.create_adapter("ads", "google", credentials={
    "developer_token": "Abc123...",
    "access_token": "ya29....",
    "customer_id": "123-456-7890",
    "login_customer_id": "987-654-3210",  # only when going through an MCC
})

campaign = ads.create_campaign(AdCampaign(
    name="Brand search", objective=AdObjective.TRAFFIC, daily_budget=Decimal("30"),
))
group = ads.create_ad_group(AdGroup(
    campaign_id=campaign.id, name="Brand terms", bid_amount=Decimal("0.40"),
))
ad = ads.create_ad(Ad(
    ad_group_id=group.id, name="RSA v1",
    creative=AdCreative(title="Buy Direct & Save", body="Free shipping over 50 RON.",
                        landing_url="https://example.com"),
))

from datetime import datetime, timedelta
rows = ads.get_insights(AdInsightsLevel.AD, since=datetime.now() - timedelta(days=30), until=datetime.now())
for row in rows:
    print(row.entity_id, row.impressions, row.clicks, row.spend, row.conversions)
```

## Uploading media

```python
from bapp_connectors.core.dto.ads import AdMediaAsset, AdMediaType

asset = ads.upload_media(AdMediaAsset(media_type=AdMediaType.IMAGE,
                                      file_path="/img/banner.png"))
# asset.id is the Google asset resourceName, usable in display/PMax formats
```

- **Images** upload from `file_path`/`content` as IMAGE assets (Google needs
  the bytes inline; URLs are rejected).
- **Video** raises `UnsupportedFeatureError` — Google Ads doesn't host video.
  Upload to YouTube instead (the social/youtube provider's `publish_post`
  works) and reference the YouTube video id.
- **`create_creative` raises `UnsupportedFeatureError`** — search-ad content
  is inline: `create_ad` builds the responsive search ad directly from
  `AdCreative(title, body, landing_url)`.

## Notes & limitations

- **Budgets/bids** are whole-currency `Decimal`s, converted to Google micros
  automatically.
- **Budget updates**: a Google campaign budget is a separate resource;
  `update_campaign` rejects `daily_budget` changes (set it at create time, or
  manage the budget resource directly).
- **Ads are immutable** on Google — `update_ad` only accepts status changes;
  create a new ad to change copy. Responsive search ads in production want ≥3
  headlines and ≥2 descriptions for best serving; the adapter sends what the
  creative provides.
- **Targeting** (locations, audiences, keywords) is attached via separate
  criteria resources on Google and isn't wrapped yet — `create_ad_group`
  covers name/bid/status; add criteria through the API directly for now.
- Deleting maps to Google's `REMOVED` state (irreversible, entities stay
  queryable).
