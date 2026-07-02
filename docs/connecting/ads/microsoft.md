# Connecting Microsoft Ads (Bing)

Creates and manages search campaigns and reads performance via the
**Bing Ads API v13** (Campaign Management + Reporting SOAP services — the
adapter speaks SOAP internally; you use the same `AdsPort` as everywhere else).

| | |
|---|---|
| Provider key | `ads` / `microsoft` |
| Auth | OAuth2 access token + developer token (SOAP headers) |
| Credentials | `developer_token`, `access_token`, `customer_id`, `account_id`; `client_id` + `client_secret` for OAuth |
| Settings | `currency` (default `USD`, spend label) |
| Capabilities | `OAuthCapability` |

## What you get

- Campaigns / ad groups / ads: list, get, create, update, and
  pause/resume/delete via `set_*_status`
- Ad creation builds a **responsive search ad** from
  `AdCreative(title, body, landing_url)`
- `get_insights()` at account / campaign / ad-group / ad level via the
  Reporting service: impressions, clicks, spend, CTR, average CPC, conversions

## Getting credentials

1. **Developer token** — in the Microsoft Advertising web UI (with a Manager
   account), go to Settings → Developer settings and request a token. New
   tokens start sandbox/own-accounts-only; apply for production access.
2. **OAuth2** — register an app in
   [Microsoft Entra admin center](https://entra.microsoft.com/) (App
   registrations), add the redirect URI, and run the flow with scopes
   `https://ads.microsoft.com/msads.manage` + `offline_access`. The adapter
   implements it (add `client_id` + `client_secret`): `get_authorize_url` →
   `exchange_code_for_token` → `refresh_token()` (standard refresh grant;
   access tokens last ~1 hour).
3. **customer_id** and **account_id** — visible in the Microsoft Advertising
   UI URL (`cid=` and `aid=`) or under Settings → Accounts.

## Quick start

```python
from decimal import Decimal
from bapp_connectors.core.dto.ads import Ad, AdCampaign, AdCreative, AdGroup, AdInsightsLevel, AdObjective
from bapp_connectors.core.registry import registry
import bapp_connectors.providers.ads.microsoft  # noqa: F401

ads = registry.create_adapter("ads", "microsoft", credentials={
    "developer_token": "1234ABCD...",
    "access_token": "EwB...",
    "customer_id": "251234567",
    "account_id": "181234567",
})

campaign = ads.create_campaign(AdCampaign(
    name="Brand search", objective=AdObjective.TRAFFIC, daily_budget=Decimal("25"),
))
group = ads.create_ad_group(AdGroup(campaign_id=campaign.id, name="Brand terms",
                                    bid_amount=Decimal("0.35")))
ad = ads.create_ad(Ad(
    ad_group_id=group.id, name="RSA v1",
    creative=AdCreative(title="Buy Direct & Save", body="Free shipping over 50 RON.",
                        landing_url="https://example.com"),
))

for row in ads.get_insights(AdInsightsLevel.CAMPAIGN, entity_id=campaign.id):
    print(row.impressions, row.clicks, row.spend, row.conversions)
```

## Notes & limitations

- **Insights are summary-aggregated** (one row per entity over the period, no
  per-day breakdown) and run Bing's async report flow internally
  (submit → poll → download); expect a few seconds of latency.
- **Ad edits are status-only** — like Google, change copy by creating a new ad.
  The adapter writes responsive search ads with one headline/description; the
  live API wants ≥3 headlines / ≥2 descriptions for best serving — pass longer
  creatives for production use.
- Listing ad groups/ads requires their parent id (`campaign_id` /
  `ad_group_id`) — Microsoft scopes these per parent.
- Keyword/audience targeting and Shopping campaign setup aren't wrapped yet;
  campaigns default to the Search type.
- A missing daily budget on create defaults to 10 currency units (Bing
  requires a budget).
