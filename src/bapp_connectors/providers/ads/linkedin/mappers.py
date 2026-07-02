"""
LinkedIn Marketing API <-> DTO mappers.

Hierarchy mapping (see the adapter docstring): a LinkedIn *campaign group* is
the framework's AdCampaign, a LinkedIn *campaign* is the AdGroup, and a
LinkedIn *creative* is the Ad.

Money: LinkedIn amounts are ``{"amount": "10.5", "currencyCode": "USD"}``
records in currency units; runSchedule timestamps are epoch milliseconds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
    AdTargeting,
)
from bapp_connectors.core.errors import ValidationError

DEFAULT_CURRENCY = "USD"
DEFAULT_BID = Decimal(2)
# Default locations facet value when a draft carries no geo targeting (United States).
DEFAULT_GEO_URN = "urn:li:geo:103644278"
LOCATIONS_FACET = "urn:li:adTargetingFacet:locations"

# ── Money helpers ──


def money_to_decimal(value: dict | None) -> Decimal | None:
    """Convert a LinkedIn money record ({"amount": "10.5", "currencyCode": "USD"}) to a Decimal."""
    if not isinstance(value, dict) or value.get("amount") in (None, ""):
        return None
    try:
        return Decimal(str(value["amount"]))
    except InvalidOperation:
        return None


def money_currency(value: dict | None) -> str:
    """Extract the currency code from a LinkedIn money record."""
    if isinstance(value, dict):
        return value.get("currencyCode", "")
    return ""


def decimal_to_money(value, currency: str = DEFAULT_CURRENCY) -> dict:
    """Build a LinkedIn money record from a Decimal (or numeric) currency amount."""
    return {"amount": str(Decimal(str(value))), "currencyCode": currency or DEFAULT_CURRENCY}


# ── Status maps ──

STATUS_READ_MAP: dict[str, AdEntityStatus] = {
    "ACTIVE": AdEntityStatus.ACTIVE,
    "PAUSED": AdEntityStatus.PAUSED,
    "ARCHIVED": AdEntityStatus.ARCHIVED,
    "CANCELED": AdEntityStatus.ENDED,
    "CANCELLED": AdEntityStatus.ENDED,
    "DRAFT": AdEntityStatus.DRAFT,
    "PENDING_DELETION": AdEntityStatus.DELETED,
    "REMOVED": AdEntityStatus.DELETED,
}

# LinkedIn has no hard delete — DELETED maps to ARCHIVED (the closest terminal state).
STATUS_WRITE_MAP: dict[AdEntityStatus, str] = {
    AdEntityStatus.ACTIVE: "ACTIVE",
    AdEntityStatus.PAUSED: "PAUSED",
    AdEntityStatus.ARCHIVED: "ARCHIVED",
    AdEntityStatus.DELETED: "ARCHIVED",
}


def status_from_linkedin(value: str) -> AdEntityStatus:
    """Map a LinkedIn entity status to the normalized status."""
    return STATUS_READ_MAP.get(value, AdEntityStatus.UNKNOWN)


def status_to_linkedin(status: AdEntityStatus | str) -> str:
    """Map a normalized status to LinkedIn's enum (DELETED becomes ARCHIVED)."""
    status = AdEntityStatus(status)
    linkedin_status = STATUS_WRITE_MAP.get(status)
    if linkedin_status is None:
        raise ValidationError(f"LinkedIn Ads cannot set status '{status}'.")
    return linkedin_status


def _write_status(status: AdEntityStatus | str | None) -> str:
    """Status for create payloads — unset/unmapped statuses default to PAUSED."""
    if status and AdEntityStatus(status) in STATUS_WRITE_MAP:
        return STATUS_WRITE_MAP[AdEntityStatus(status)]
    return "PAUSED"


# ── Shared helpers ──


def urn_tail(urn: str) -> str:
    """Return the id part of a URN: "urn:li:sponsoredCampaign:42" -> "42"."""
    return str(urn).rsplit(":", 1)[-1]


def _ms_to_datetime(value) -> datetime | None:
    """Convert an epoch-milliseconds timestamp to a UTC datetime."""
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _datetime_to_ms(value: datetime) -> int:
    """Convert a datetime to epoch milliseconds."""
    return int(value.timestamp() * 1000)


def _run_schedule(start: datetime | None, end: datetime | None) -> dict:
    """Build a runSchedule record; start defaults to now when absent."""
    schedule: dict = {"start": _datetime_to_ms(start or datetime.now(UTC))}
    if end:
        schedule["end"] = _datetime_to_ms(end)
    return schedule


# ── Campaign groups (framework AdCampaign) ──


def campaign_from_group(group: dict) -> AdCampaign:
    """Map a raw LinkedIn campaign group to the AdCampaign DTO."""
    schedule = group.get("runSchedule") or {}
    return AdCampaign(
        id=str(group.get("id", "")),
        name=group.get("name", ""),
        status=status_from_linkedin(group.get("status", "")),
        lifetime_budget=money_to_decimal(group.get("totalBudget")),
        currency=money_currency(group.get("totalBudget")),
        start_time=_ms_to_datetime(schedule.get("start")),
        end_time=_ms_to_datetime(schedule.get("end")),
    )


def campaign_group_to_payload(campaign: AdCampaign, account_urn: str) -> dict:
    """Build a LinkedIn campaign group create payload from an AdCampaign draft."""
    payload: dict = {
        "account": account_urn,
        "name": campaign.name,
        "status": _write_status(campaign.status),
        "runSchedule": _run_schedule(campaign.start_time, campaign.end_time),
    }
    if campaign.lifetime_budget is not None:
        payload["totalBudget"] = decimal_to_money(campaign.lifetime_budget, campaign.currency)
    return payload


def campaign_group_patch(changes: dict) -> dict:
    """Map normalized AdCampaign change fields to a campaign group $set patch."""
    fields: dict = {}
    for field, value in changes.items():
        if field == "name":
            fields["name"] = value
        elif field == "status":
            fields["status"] = status_to_linkedin(value)
        elif field == "lifetime_budget":
            fields["totalBudget"] = decimal_to_money(value, changes.get("currency", DEFAULT_CURRENCY))
        elif field == "currency":
            continue  # consumed by lifetime_budget above
        else:
            raise ValidationError(f"Unsupported LinkedIn campaign update field: '{field}'.")
    if not fields:
        raise ValidationError("No supported campaign fields to update.")
    return fields


# ── Campaigns (framework AdGroup) ──


def _geo_urns_from_criteria(criteria: dict) -> list[str]:
    """Collect location geo URNs from a targetingCriteria include tree."""
    geo_urns: list[str] = []
    for clause in (criteria.get("include") or {}).get("and", []):
        facets = clause.get("or") or {}
        geo_urns.extend(facets.get(LOCATIONS_FACET, []))
    return geo_urns


def targeting_from_criteria(criteria: dict) -> AdTargeting:
    """Map a LinkedIn targetingCriteria tree to the normalized AdTargeting.

    LinkedIn locations are geo URNs (urn:li:geo:*), not ISO country codes, so
    they land in ``targeting.extra["geo_urns"]`` rather than ``countries``.
    """
    return AdTargeting(extra={"geo_urns": _geo_urns_from_criteria(criteria)})


def targeting_to_criteria(targeting: AdTargeting | None) -> dict:
    """Build a LinkedIn targetingCriteria tree from the normalized AdTargeting.

    Uses ``targeting.extra["geo_urns"]`` when present, falling back to the
    default geo (LinkedIn campaigns require at least one location).
    """
    geo_urns = list((targeting.extra if targeting else {}).get("geo_urns") or []) or [DEFAULT_GEO_URN]
    return {"include": {"and": [{"or": {LOCATIONS_FACET: geo_urns}}]}}


def ad_group_from_campaign(campaign: dict) -> AdGroup:
    """Map a raw LinkedIn campaign to the AdGroup DTO."""
    schedule = campaign.get("runSchedule") or {}
    criteria = campaign.get("targetingCriteria") or {}
    return AdGroup(
        id=str(campaign.get("id", "")),
        campaign_id=urn_tail(campaign.get("campaignGroup", "")),
        name=campaign.get("name", ""),
        status=status_from_linkedin(campaign.get("status", "")),
        daily_budget=money_to_decimal(campaign.get("dailyBudget")),
        lifetime_budget=money_to_decimal(campaign.get("totalBudget")),
        bid_amount=money_to_decimal(campaign.get("unitCost")),
        targeting=targeting_from_criteria(criteria) if criteria else None,
        start_time=_ms_to_datetime(schedule.get("start")),
        end_time=_ms_to_datetime(schedule.get("end")),
    )


def campaign_to_payload(ad_group: AdGroup, account_urn: str, currency: str = DEFAULT_CURRENCY) -> dict:
    """Build a LinkedIn campaign create payload from an AdGroup draft."""
    payload: dict = {
        "account": account_urn,
        "campaignGroup": f"urn:li:sponsoredCampaignGroup:{ad_group.campaign_id}",
        "name": ad_group.name,
        "status": _write_status(ad_group.status),
        "type": "SPONSORED_UPDATES",
        "costType": "CPC",
        "unitCost": decimal_to_money(ad_group.bid_amount if ad_group.bid_amount is not None else DEFAULT_BID, currency),
        "locale": {"country": "US", "language": "en"},
        "runSchedule": _run_schedule(ad_group.start_time, ad_group.end_time),
        "targetingCriteria": targeting_to_criteria(ad_group.targeting),
    }
    if ad_group.daily_budget is not None:
        payload["dailyBudget"] = decimal_to_money(ad_group.daily_budget, currency)
    if ad_group.lifetime_budget is not None:
        payload["totalBudget"] = decimal_to_money(ad_group.lifetime_budget, currency)
    return payload


def campaign_patch(changes: dict) -> dict:
    """Map normalized AdGroup change fields to a campaign $set patch."""
    fields: dict = {}
    for field, value in changes.items():
        if field == "name":
            fields["name"] = value
        elif field == "status":
            fields["status"] = status_to_linkedin(value)
        elif field == "daily_budget":
            fields["dailyBudget"] = decimal_to_money(value)
        elif field == "lifetime_budget":
            fields["totalBudget"] = decimal_to_money(value)
        elif field == "bid_amount":
            fields["unitCost"] = decimal_to_money(value)
        elif field == "targeting":
            targeting = AdTargeting.model_validate(value) if isinstance(value, dict) else value
            fields["targetingCriteria"] = targeting_to_criteria(targeting)
        else:
            raise ValidationError(f"Unsupported LinkedIn ad group update field: '{field}'.")
    if not fields:
        raise ValidationError("No supported ad group fields to update.")
    return fields


# ── Creatives (framework Ad) ──


def ad_from_creative(creative: dict) -> Ad:
    """Map a raw LinkedIn creative to the Ad DTO.

    Creatives have no name of their own — the id doubles as the name. The
    referenced post URN (content.reference) is preserved in
    ``creative.extra["content_reference"]``.
    """
    creative_urn = str(creative.get("id", ""))
    ad_id = urn_tail(creative_urn)
    reference = (creative.get("content") or {}).get("reference", "")
    return Ad(
        id=ad_id,
        ad_group_id=urn_tail(creative.get("campaign", "")),
        name=ad_id,
        status=status_from_linkedin(creative.get("intendedStatus", "")),
        creative=AdCreative(
            id=creative_urn,
            extra={"content_reference": reference} if reference else {},
        ),
    )


def _content_reference(ad: Ad) -> str:
    """Resolve the post URN a creative should reference, or raise."""
    creative = ad.creative
    if creative and creative.id.startswith("urn:"):
        return creative.id
    if creative and creative.extra.get("content_reference"):
        return str(creative.extra["content_reference"])
    if ad.extra.get("content_reference"):
        return str(ad.extra["content_reference"])
    raise ValidationError(
        "LinkedIn creatives reference an existing post: provide a content reference URN "
        "(e.g. an urn:li:share:* from a published LinkedIn post) via creative.id or "
        "extra['content_reference']."
    )


def creative_to_payload(ad: Ad, campaign_urn: str) -> dict:
    """Build a LinkedIn creative create payload from an Ad draft."""
    return {
        "campaign": campaign_urn,
        "intendedStatus": _write_status(ad.status),
        "content": {"reference": _content_reference(ad)},
    }


def creative_patch(changes: dict) -> dict:
    """Map normalized Ad change fields to a creative $set patch (status only)."""
    fields: dict = {}
    for field, value in changes.items():
        if field == "status":
            fields["intendedStatus"] = status_to_linkedin(value)
        else:
            raise ValidationError(
                f"Unsupported LinkedIn ad update field: '{field}' — creatives only allow status changes; "
                "create a new creative for content changes."
            )
    if not fields:
        raise ValidationError("No supported ad fields to update.")
    return fields


# ── Insights ──


def _date_from_record(record: dict | None) -> datetime | None:
    """Build a datetime from a Restli date record {"year": Y, "month": M, "day": D}."""
    if not record:
        return None
    try:
        return datetime(int(record["year"]), int(record["month"]), int(record["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def insights_from_row(row: dict, level: AdInsightsLevel) -> AdInsights:
    """Map one adAnalytics element to the universal AdInsights DTO.

    LinkedIn exposes raw counters (impressions, clicks, spend, conversions);
    ctr/cpc/cpm are derived here when the inputs allow it.
    """
    impressions = int(row["impressions"]) if row.get("impressions") is not None else None
    clicks = int(row["clicks"]) if row.get("clicks") is not None else None
    spend = Decimal(str(row["costInLocalCurrency"])) if row.get("costInLocalCurrency") is not None else None

    ctr = (clicks / impressions * 100) if impressions and clicks is not None else None
    cpc = (spend / clicks) if clicks and spend is not None else None
    cpm = (spend / impressions * 1000) if impressions and spend is not None else None

    conversions = row.get("externalWebsiteConversions")
    date_range = row.get("dateRange") or {}
    pivot_values = row.get("pivotValues") or []

    return AdInsights(
        level=level,
        entity_id=urn_tail(pivot_values[0]) if pivot_values else "",
        date_start=_date_from_record(date_range.get("start")),
        date_stop=_date_from_record(date_range.get("end")),
        impressions=impressions,
        clicks=clicks,
        spend=spend,
        ctr=ctr,
        cpc=cpc,
        cpm=cpm,
        conversions=float(conversions) if conversions is not None else None,
    )
