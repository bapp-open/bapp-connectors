"""
Google Ads advertising adapter — implements AdsPort.

Uses the Google Ads REST API v17 (not the gRPC surface): reads are GAQL
queries via ``googleAds:search``, writes are per-resource ``:mutate``
endpoints (campaignBudgets, campaigns, adGroups, adGroupAds, assets).

Normalized mapping: Google "campaign" -> AdCampaign, "ad group" -> AdGroup,
"ad group ad" -> Ad. Money is micros in the account currency. OAuth token
refresh is handled outside the adapter — pass a valid ``access_token``
credential.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import CreativeUploadCapability
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
    AdMediaAsset,
    AdMediaType,
    UploadedAdMedia,
)
from bapp_connectors.core.errors import ConnectorError, UnsupportedFeatureError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.providers.ads.google.client import GoogleAdsClient
from bapp_connectors.providers.ads.google.errors import extract_ad_id, extract_resource_id, not_found
from bapp_connectors.providers.ads.google.manifest import manifest
from bapp_connectors.providers.ads.google.mappers import (
    STATUS_WRITE_MAP,
    ad_from_row,
    ad_group_from_row,
    campaign_from_row,
    decimal_to_micros,
    format_google_date,
    insights_from_row,
    objective_to_channel_type,
    status_to_google,
)

if TYPE_CHECKING:
    from datetime import datetime

# Default daily budget when creating a campaign without one: 10 currency units.
DEFAULT_BUDGET_MICROS = 10_000_000

# ── GAQL queries ──

CAMPAIGN_QUERY = (
    "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, "
    "campaign.start_date, campaign.end_date, campaign_budget.amount_micros, customer.currency_code "
    "FROM campaign"
)

AD_GROUP_QUERY = (
    "SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.cpc_bid_micros, campaign.id FROM ad_group"
)

AD_QUERY = (
    "SELECT ad_group_ad.status, ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.ad.final_urls, "
    "ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions, "
    "ad_group.id, campaign.id FROM ad_group_ad"
)

CONNECTION_TEST_QUERY = "SELECT customer.id, customer.descriptive_name, customer.currency_code FROM customer LIMIT 1"

INSIGHTS_METRICS = (
    "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.ctr, metrics.average_cpc, "
    "metrics.average_cpm, metrics.conversions, metrics.conversions_value, metrics.video_views"
)

INSIGHTS_RESOURCES = {
    AdInsightsLevel.ACCOUNT: "customer",
    AdInsightsLevel.CAMPAIGN: "campaign",
    AdInsightsLevel.AD_GROUP: "ad_group",
    AdInsightsLevel.AD: "ad_group_ad",
}

INSIGHTS_ID_FIELDS = {
    AdInsightsLevel.ACCOUNT: "customer.id",
    AdInsightsLevel.CAMPAIGN: "campaign.id",
    AdInsightsLevel.AD_GROUP: "ad_group.id",
    AdInsightsLevel.AD: "ad_group_ad.ad.id",
}


def _numeric_id(entity: str, value: str) -> str:
    """Validate an id interpolated into GAQL (Google entity ids are numeric)."""
    value = str(value)
    if not value.isdigit():
        raise ValidationError(f"Invalid Google Ads {entity} id '{value}': numeric id expected.")
    return value


class GoogleAdsAdapter(AdsPort, CreativeUploadCapability):
    """
    Google Ads REST API v17 adapter.

    Implements AdsPort: campaign / ad group / ad CRUD plus the universal
    insights interface. Google particularities:

    - Budgets live on a separate ``campaignBudget`` resource; create_campaign
      creates one implicitly, update_campaign rejects budget changes.
    - DELETED maps to Google's remove operation (status REMOVED); removed
      entities stay queryable.
    - Ads are immutable once created — only status can change.
    - CreativeUploadCapability covers image assets only (``assets:mutate``);
      video hosting and standalone creatives don't exist on Google Ads.
    """

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = manifest.settings.apply_defaults(config or {})

        if http_client is None:
            # Auth headers are built per call by GoogleAdsClient, hence NoAuth here.
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=NoAuth(),
                provider_name="google_ads",
            )

        self.client = GoogleAdsClient(
            http_client=http_client,
            developer_token=credentials.get("developer_token", ""),
            access_token=credentials.get("access_token", ""),
            customer_id=credentials.get("customer_id", ""),
            login_customer_id=credentials.get("login_customer_id", "") or "",
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            rows, _ = self._search(CONNECTION_TEST_QUERY)
            if not rows:
                return ConnectionTestResult(success=False, message="No Google Ads customer returned.")
            customer = rows[0].get("customer", {})
            name = customer.get("descriptiveName") or customer.get("id", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to Google Ads account {name}",
                details=customer,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── Internal helpers ──

    def _search(self, query: str, page_token: str | None = None) -> tuple[list[dict], str | None]:
        """Run a GAQL query, returning (rows, next_page_token)."""
        response = self.client.search(query, page_token=page_token)
        return response.get("results", []), response.get("nextPageToken")

    def _mutated_resource_name(self, response: dict) -> str:
        """Extract the resourceName of the first mutate result."""
        results = response.get("results", [])
        if not results:
            raise ValidationError("Google Ads mutate returned no results.")
        return results[0].get("resourceName", "")

    def _campaign_resource(self, campaign_id: str) -> str:
        return f"customers/{self.client.customer_id}/campaigns/{_numeric_id('campaign', campaign_id)}"

    def _ad_group_resource(self, ad_group_id: str) -> str:
        return f"customers/{self.client.customer_id}/adGroups/{_numeric_id('ad group', ad_group_id)}"

    def _ad_group_ad_resource(self, ad_group_id: str, ad_id: str) -> str:
        return (
            f"customers/{self.client.customer_id}/adGroupAds/"
            f"{_numeric_id('ad group', ad_group_id)}~{_numeric_id('ad', ad_id)}"
        )

    @staticmethod
    def _write_status(status: AdEntityStatus, default: AdEntityStatus = AdEntityStatus.PAUSED) -> str:
        """Google status for create operations — falls back to PAUSED for unset/unmapped statuses."""
        if status in STATUS_WRITE_MAP:
            return STATUS_WRITE_MAP[status]
        return STATUS_WRITE_MAP[default]

    # ── Campaigns ──

    def list_campaigns(self, cursor: str | None = None) -> PaginatedResult[AdCampaign]:
        rows, next_token = self._search(f"{CAMPAIGN_QUERY} ORDER BY campaign.id", page_token=cursor)
        return PaginatedResult(
            items=[campaign_from_row(row) for row in rows],
            cursor=next_token,
            has_more=bool(next_token),
        )

    def get_campaign(self, campaign_id: str) -> AdCampaign:
        query = f"{CAMPAIGN_QUERY} WHERE campaign.id = {_numeric_id('campaign', campaign_id)}"
        rows, _ = self._search(query)
        if not rows:
            not_found("campaign", campaign_id)
        return campaign_from_row(rows[0])

    def create_campaign(self, campaign: AdCampaign) -> AdCampaign:
        budget_micros = (
            decimal_to_micros(campaign.daily_budget) if campaign.daily_budget is not None else DEFAULT_BUDGET_MICROS
        )
        budget_response = self.client.mutate(
            "campaignBudgets",
            [
                {
                    "create": {
                        "name": f"{campaign.name} budget",
                        "amountMicros": budget_micros,
                        "deliveryMethod": "STANDARD",
                        "explicitlyShared": False,
                    }
                }
            ],
        )
        budget_resource = self._mutated_resource_name(budget_response)

        create_op: dict = {
            "name": campaign.name,
            "status": self._write_status(campaign.status),
            "advertisingChannelType": objective_to_channel_type(campaign.objective),
            "campaignBudget": budget_resource,
            "manualCpc": {},
        }
        if campaign.start_time:
            create_op["startDate"] = format_google_date(campaign.start_time)
        if campaign.end_time:
            create_op["endDate"] = format_google_date(campaign.end_time)

        response = self.client.mutate("campaigns", [{"create": create_op}])
        campaign_id = extract_resource_id(self._mutated_resource_name(response))
        return self.get_campaign(campaign_id)

    def update_campaign(self, campaign_id: str, changes: dict) -> AdCampaign:
        update: dict = {"resourceName": self._campaign_resource(campaign_id)}
        mask: list[str] = []
        for field, value in changes.items():
            if field in ("daily_budget", "lifetime_budget"):
                raise ValidationError(
                    "Google Ads budgets live on a separate campaignBudget resource; "
                    "budget changes are not supported via update_campaign."
                )
            if field == "name":
                update["name"] = value
                mask.append("name")
            elif field == "status":
                update["status"] = status_to_google(value)
                mask.append("status")
            elif field == "start_time":
                update["startDate"] = format_google_date(value)
                mask.append("startDate")
            elif field == "end_time":
                update["endDate"] = format_google_date(value)
                mask.append("endDate")
            else:
                raise ValidationError(f"Unsupported Google Ads campaign update field: '{field}'.")
        if not mask:
            raise ValidationError("No supported campaign fields to update.")
        self.client.mutate("campaigns", [{"update": update, "updateMask": ",".join(mask)}])
        return self.get_campaign(campaign_id)

    def set_campaign_status(self, campaign_id: str, status: AdEntityStatus) -> AdCampaign:
        status = AdEntityStatus(status)
        resource_name = self._campaign_resource(campaign_id)
        if status == AdEntityStatus.DELETED:
            self.client.mutate("campaigns", [{"remove": resource_name}])
            # A removed campaign is still queryable — re-fetch for the last-known DTO.
            try:
                campaign = self.get_campaign(campaign_id)
            except ConnectorError:
                return AdCampaign(id=str(campaign_id), name="", status=AdEntityStatus.DELETED)
            return campaign.model_copy(update={"status": AdEntityStatus.DELETED})
        update = {"resourceName": resource_name, "status": status_to_google(status)}
        self.client.mutate("campaigns", [{"update": update, "updateMask": "status"}])
        return self.get_campaign(campaign_id)

    # ── Ad groups ──

    def list_ad_groups(self, campaign_id: str | None = None, cursor: str | None = None) -> PaginatedResult[AdGroup]:
        query = AD_GROUP_QUERY
        if campaign_id:
            query += f" WHERE campaign.id = {_numeric_id('campaign', campaign_id)}"
        rows, next_token = self._search(query, page_token=cursor)
        return PaginatedResult(
            items=[ad_group_from_row(row) for row in rows],
            cursor=next_token,
            has_more=bool(next_token),
        )

    def get_ad_group(self, ad_group_id: str) -> AdGroup:
        query = f"{AD_GROUP_QUERY} WHERE ad_group.id = {_numeric_id('ad group', ad_group_id)}"
        rows, _ = self._search(query)
        if not rows:
            not_found("ad group", ad_group_id)
        return ad_group_from_row(rows[0])

    def create_ad_group(self, ad_group: AdGroup) -> AdGroup:
        create_op: dict = {
            "name": ad_group.name,
            "campaign": self._campaign_resource(ad_group.campaign_id),
            "status": self._write_status(ad_group.status),
            "type": "SEARCH_STANDARD",
        }
        if ad_group.bid_amount is not None:
            create_op["cpcBidMicros"] = decimal_to_micros(ad_group.bid_amount)
        response = self.client.mutate("adGroups", [{"create": create_op}])
        ad_group_id = extract_resource_id(self._mutated_resource_name(response))
        return self.get_ad_group(ad_group_id)

    def update_ad_group(self, ad_group_id: str, changes: dict) -> AdGroup:
        update: dict = {"resourceName": self._ad_group_resource(ad_group_id)}
        mask: list[str] = []
        for field, value in changes.items():
            if field == "name":
                update["name"] = value
                mask.append("name")
            elif field == "status":
                update["status"] = status_to_google(value)
                mask.append("status")
            elif field == "bid_amount":
                update["cpcBidMicros"] = decimal_to_micros(value)
                mask.append("cpcBidMicros")
            else:
                raise ValidationError(f"Unsupported Google Ads ad group update field: '{field}'.")
        if not mask:
            raise ValidationError("No supported ad group fields to update.")
        self.client.mutate("adGroups", [{"update": update, "updateMask": ",".join(mask)}])
        return self.get_ad_group(ad_group_id)

    def set_ad_group_status(self, ad_group_id: str, status: AdEntityStatus) -> AdGroup:
        status = AdEntityStatus(status)
        resource_name = self._ad_group_resource(ad_group_id)
        if status == AdEntityStatus.DELETED:
            self.client.mutate("adGroups", [{"remove": resource_name}])
            try:
                ad_group = self.get_ad_group(ad_group_id)
            except ConnectorError:
                return AdGroup(id=str(ad_group_id), campaign_id="", name="", status=AdEntityStatus.DELETED)
            return ad_group.model_copy(update={"status": AdEntityStatus.DELETED})
        update = {"resourceName": resource_name, "status": status_to_google(status)}
        self.client.mutate("adGroups", [{"update": update, "updateMask": "status"}])
        return self.get_ad_group(ad_group_id)

    # ── Ads ──

    def list_ads(self, ad_group_id: str | None = None, cursor: str | None = None) -> PaginatedResult[Ad]:
        query = AD_QUERY
        if ad_group_id:
            query += f" WHERE ad_group.id = {_numeric_id('ad group', ad_group_id)}"
        rows, next_token = self._search(query, page_token=cursor)
        return PaginatedResult(
            items=[ad_from_row(row) for row in rows],
            cursor=next_token,
            has_more=bool(next_token),
        )

    def get_ad(self, ad_id: str) -> Ad:
        query = f"{AD_QUERY} WHERE ad_group_ad.ad.id = {_numeric_id('ad', ad_id)}"
        rows, _ = self._search(query)
        if not rows:
            not_found("ad", ad_id)
        return ad_from_row(rows[0])

    def create_ad(self, ad: Ad) -> Ad:
        creative = ad.creative
        if creative is None or not (creative.title and creative.body and creative.landing_url):
            raise ValidationError(
                "Google Ads responsive search ads require a creative with title, body, and landing_url."
            )
        create_op = {
            "adGroup": self._ad_group_resource(ad.ad_group_id),
            "status": self._write_status(ad.status),
            "ad": {
                "name": ad.name,
                "finalUrls": [creative.landing_url],
                "responsiveSearchAd": {
                    "headlines": [{"text": creative.title}],
                    "descriptions": [{"text": creative.body}],
                },
            },
        }
        response = self.client.mutate("adGroupAds", [{"create": create_op}])
        # The created resourceName is "customers/{cid}/adGroupAds/{ad_group_id}~{ad_id}".
        ad_id_created = extract_ad_id(self._mutated_resource_name(response))
        return self.get_ad(ad_id_created)

    def update_ad(self, ad_id: str, changes: dict) -> Ad:
        unsupported = [field for field in changes if field != "status"]
        if unsupported:
            raise ValidationError(
                "Google ads are immutable once created — only 'status' can be updated; "
                f"create a new ad for content changes (got: {', '.join(sorted(unsupported))})."
            )
        if "status" not in changes:
            raise ValidationError("No supported ad fields to update.")
        return self.set_ad_status(ad_id, changes["status"])

    def set_ad_status(self, ad_id: str, status: AdEntityStatus) -> Ad:
        status = AdEntityStatus(status)
        # adGroupAds are addressed by "{ad_group_id}~{ad_id}" — look up the ad group first.
        current = self.get_ad(ad_id)
        resource_name = self._ad_group_ad_resource(current.ad_group_id, ad_id)
        if status == AdEntityStatus.DELETED:
            self.client.mutate("adGroupAds", [{"remove": resource_name}])
            return current.model_copy(update={"status": AdEntityStatus.DELETED})
        update = {"resourceName": resource_name, "status": status_to_google(status)}
        self.client.mutate("adGroupAds", [{"update": update, "updateMask": "status"}])
        return self.get_ad(ad_id)

    # ── CreativeUploadCapability ──

    def upload_media(self, asset: AdMediaAsset) -> UploadedAdMedia:
        """Upload an image to the Google Ads asset library via ``assets:mutate``.

        Google needs the image data inline (base64), so provide ``content``
        bytes or a local ``file_path`` — a ``url``-only asset is rejected.
        The created IMAGE asset is usable for display / Performance Max
        formats managed outside this adapter; responsive search ads created
        by create_ad are text-only and don't reference it.
        """
        media_type = AdMediaType(asset.media_type)
        if media_type == AdMediaType.VIDEO:
            raise UnsupportedFeatureError(
                "Google Ads cannot host video files — upload the video to YouTube "
                "(e.g. via the social/youtube provider's publish capability) and "
                "create a YOUTUBE_VIDEO asset from the video id instead."
            )
        if asset.content is not None:
            data = asset.content
        elif asset.file_path:
            data = Path(asset.file_path).read_bytes()
        else:
            raise ValidationError(
                "Google Ads image assets require the image data inline — provide "
                "'content' bytes or a local 'file_path'; Google cannot fetch from a URL."
            )
        create_op = {
            "name": asset.filename or "image asset",
            "type": "IMAGE",
            "imageAsset": {"data": base64.b64encode(data).decode("ascii")},
        }
        response = self.client.mutate("assets", [{"create": create_op}])
        # The created resourceName is "customers/{cid}/assets/{asset_id}".
        resource_name = self._mutated_resource_name(response)
        return UploadedAdMedia(
            id=resource_name,
            media_type=AdMediaType.IMAGE,
            extra={"asset_id": extract_resource_id(resource_name)},
        )

    def create_creative(self, creative: AdCreative, media: UploadedAdMedia | None = None) -> AdCreative:
        """Not available on Google Ads — always raises UnsupportedFeatureError.

        Image assets uploaded via upload_media are usable for display /
        Performance Max formats managed outside this adapter.
        """
        raise UnsupportedFeatureError(
            "Google search ads have no standalone creative resource — ad content is "
            "inline in create_ad (a responsive search ad built from AdCreative "
            "title/body/landing_url)."
        )

    # ── Universal insights ──

    def get_insights(
        self,
        level: AdInsightsLevel,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AdInsights]:
        level = AdInsightsLevel(level)
        resource = INSIGHTS_RESOURCES[level]
        id_field = INSIGHTS_ID_FIELDS[level]

        conditions: list[str] = []
        if since and until:
            conditions.append(f"segments.date BETWEEN '{format_google_date(since)}' AND '{format_google_date(until)}'")
        if entity_id and level != AdInsightsLevel.ACCOUNT:
            conditions.append(f"{id_field} = {_numeric_id(level.value, entity_id)}")

        query = f"SELECT {id_field}, customer.currency_code, {INSIGHTS_METRICS} FROM {resource}"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        rows, _ = self._search(query)
        currency = self.config.get("currency", "USD")
        return [insights_from_row(row, level, currency) for row in rows]
