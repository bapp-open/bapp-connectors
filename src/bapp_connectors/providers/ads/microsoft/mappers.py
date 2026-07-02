"""
Microsoft Ads (Bing Ads) <-> DTO mappers.

Converts between parsed Bing Ads API v13 SOAP payloads (plain dicts with
PascalCase keys, produced by the client) and normalized framework DTOs.
Money is plain currency units (not micros), always in the account currency.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation

from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
    AdObjective,
)
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.ads.microsoft.models import (
    MicrosoftAd,
    MicrosoftAdGroup,
    MicrosoftCampaign,
)

# Bing requires a daily budget on campaign creation: 10 currency units, like Google.
DEFAULT_DAILY_BUDGET = "10"
DAILY_BUDGET_TYPE = "DailyBudgetStandard"

# ── Status ──

STATUS_READ_MAP = {
    "Active": AdEntityStatus.ACTIVE,
    "Paused": AdEntityStatus.PAUSED,
    "Deleted": AdEntityStatus.DELETED,
    "Suspended": AdEntityStatus.PAUSED,
    "BudgetPaused": AdEntityStatus.PAUSED,
    "Expired": AdEntityStatus.ENDED,
}

STATUS_WRITE_MAP = {
    AdEntityStatus.ACTIVE: "Active",
    AdEntityStatus.PAUSED: "Paused",
    AdEntityStatus.DELETED: "Deleted",
}


def status_from_ms(value: str) -> AdEntityStatus:
    """Map a Bing entity status to the normalized status."""
    return STATUS_READ_MAP.get(value, AdEntityStatus.UNKNOWN)


def status_to_ms(status: AdEntityStatus | str) -> str:
    """Map a normalized status to Bing's enum (Active/Paused/Deleted only)."""
    status = AdEntityStatus(status)
    ms_status = STATUS_WRITE_MAP.get(status)
    if ms_status is None:
        raise ValidationError(f"Microsoft Ads cannot set status '{status}' (supported: active, paused, deleted).")
    return ms_status


def write_status(status: AdEntityStatus | str, default: AdEntityStatus = AdEntityStatus.PAUSED) -> str:
    """Bing status for create operations — falls back to PAUSED for unset/unmapped statuses."""
    status = AdEntityStatus(status)
    return STATUS_WRITE_MAP.get(status, STATUS_WRITE_MAP[default])


# ── Objective <-> CampaignType heuristic ──

CAMPAIGN_TYPE_READ_MAP = {
    "Search": AdObjective.TRAFFIC,
    "Shopping": AdObjective.SALES,
    "Audience": AdObjective.AWARENESS,
    "PerformanceMax": AdObjective.SALES,
}

OBJECTIVE_WRITE_MAP = {
    AdObjective.TRAFFIC: "Search",
    AdObjective.SALES: "Shopping",
    AdObjective.AWARENESS: "Audience",
}


def objective_from_campaign_type(campaign_type: str) -> AdObjective:
    """Map Bing's CampaignType to a normalized objective (heuristic)."""
    return CAMPAIGN_TYPE_READ_MAP.get(campaign_type, AdObjective.OTHER)


def objective_to_campaign_type(objective: AdObjective | str | None) -> str:
    """Map a normalized objective to Bing's CampaignType (heuristic, defaults to Search)."""
    if objective is None:
        return "Search"
    return OBJECTIVE_WRITE_MAP.get(AdObjective(objective), "Search")


# ── Dates (Bing "Date" complex type: Day/Month/Year elements) ──


def date_from_ms(value: dict | None) -> datetime | None:
    """Parse a Bing Date dict ({"Day", "Month", "Year"}) into a datetime."""
    if not value:
        return None
    try:
        return datetime(int(value["Year"]), int(value["Month"]), int(value["Day"]))
    except (KeyError, TypeError, ValueError):
        return None


def date_to_ms(value: datetime) -> dict:
    """Format a datetime as a Bing Date dict (emitted as Day/Month/Year elements)."""
    return {"Day": str(value.day), "Month": str(value.month), "Year": str(value.year)}


# ── Money ──


def _decimal_or_none(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


# ── Campaigns ──


def campaign_from_ms(data: dict) -> AdCampaign:
    """Map a parsed ``Campaign`` element to an AdCampaign DTO."""
    parsed = MicrosoftCampaign.model_validate(data)
    return AdCampaign(
        id=str(parsed.Id),
        name=parsed.Name,
        status=status_from_ms(parsed.Status),
        objective=objective_from_campaign_type(parsed.CampaignType),
        daily_budget=_decimal_or_none(parsed.DailyBudget),
        extra={
            "campaign_type": parsed.CampaignType,
            "budget_type": parsed.BudgetType,
            "time_zone": parsed.TimeZone,
        },
    )


def campaign_to_ms(campaign: AdCampaign) -> dict:
    """Map an AdCampaign draft to a Bing Campaign dict for AddCampaigns.

    TimeZone is omitted (Bing falls back to the account time zone) unless
    provided via ``extra["time_zone"]``. A missing daily budget defaults to
    10 currency units — Bing requires one.
    """
    budget = campaign.daily_budget if campaign.daily_budget is not None else DEFAULT_DAILY_BUDGET
    data = {
        "BudgetType": DAILY_BUDGET_TYPE,
        "CampaignType": objective_to_campaign_type(campaign.objective),
        "DailyBudget": str(budget),
        "Name": campaign.name,
        "Status": write_status(campaign.status),
    }
    if campaign.extra.get("time_zone"):
        data["TimeZone"] = campaign.extra["time_zone"]
    return data


def campaign_changes_to_ms(changes: dict) -> dict:
    """Map normalized campaign update fields to a partial Bing Campaign dict."""
    data: dict = {}
    for field, value in changes.items():
        if field == "name":
            data["Name"] = value
        elif field == "status":
            data["Status"] = status_to_ms(value)
        elif field == "daily_budget":
            data["BudgetType"] = DAILY_BUDGET_TYPE
            data["DailyBudget"] = str(value)
        else:
            raise ValidationError(f"Unsupported Microsoft Ads campaign update field: '{field}'.")
    if not data:
        raise ValidationError("No supported campaign fields to update.")
    return data


# ── Ad groups ──


def ad_group_from_ms(data: dict, campaign_id: str) -> AdGroup:
    """Map a parsed ``AdGroup`` element to an AdGroup DTO."""
    parsed = MicrosoftAdGroup.model_validate(data)
    return AdGroup(
        id=str(parsed.Id),
        campaign_id=str(campaign_id),
        name=parsed.Name,
        status=status_from_ms(parsed.Status),
        bid_amount=_decimal_or_none(parsed.CpcBid),
        start_time=date_from_ms(parsed.StartDate),
        end_time=date_from_ms(parsed.EndDate),
    )


def ad_group_to_ms(ad_group: AdGroup) -> dict:
    """Map an AdGroup draft to a Bing AdGroup dict for AddAdGroups."""
    data: dict = {
        "Name": ad_group.name,
        "Status": write_status(ad_group.status),
    }
    if ad_group.bid_amount is not None:
        data["CpcBid"] = {"Amount": str(ad_group.bid_amount)}
    if ad_group.start_time:
        data["StartDate"] = date_to_ms(ad_group.start_time)
    if ad_group.end_time:
        data["EndDate"] = date_to_ms(ad_group.end_time)
    return data


def ad_group_changes_to_ms(changes: dict) -> dict:
    """Map normalized ad group update fields to a partial Bing AdGroup dict."""
    data: dict = {}
    for field, value in changes.items():
        if field == "name":
            data["Name"] = value
        elif field == "status":
            data["Status"] = status_to_ms(value)
        elif field == "bid_amount":
            data["CpcBid"] = {"Amount": str(value)}
        elif field == "start_time":
            data["StartDate"] = date_to_ms(value)
        elif field == "end_time":
            data["EndDate"] = date_to_ms(value)
        else:
            raise ValidationError(f"Unsupported Microsoft Ads ad group update field: '{field}'.")
    if not data:
        raise ValidationError("No supported ad group fields to update.")
    return data


# ── Ads ──


def ad_from_ms(data: dict, ad_group_id: str) -> Ad:
    """Map a parsed ``Ad`` element to an Ad DTO.

    The creative comes from the first responsive search ad headline (title),
    first description (body), and first final URL (landing_url); legacy text
    ads map Title/Text instead. Bing ads have no name — the creative title
    (or the id) doubles as the DTO name.
    """
    parsed = MicrosoftAd.model_validate(data)
    title = parsed.Headlines[0] if parsed.Headlines else parsed.Title
    body = parsed.Descriptions[0] if parsed.Descriptions else parsed.Text
    creative = AdCreative(
        title=title,
        body=body,
        landing_url=parsed.FinalUrls[0] if parsed.FinalUrls else "",
    )
    return Ad(
        id=str(parsed.Id),
        ad_group_id=str(ad_group_id),
        name=title or f"Ad {parsed.Id}",
        status=status_from_ms(parsed.Status),
        creative=creative,
        extra={"ad_type": parsed.Type},
    )


def ad_to_ms(ad: Ad) -> dict:
    """Map an Ad draft to a Bing ResponsiveSearchAd dict for AddAds.

    Simplification: one headline/description each is sent (built from
    AdCreative title/body). The live API requires at least 3 headlines and
    2 descriptions — pad the creative before pointing this at production.
    """
    creative = ad.creative
    if creative is None or not (creative.title and creative.body and creative.landing_url):
        raise ValidationError(
            "Microsoft Ads responsive search ads require a creative with title, body, and landing_url."
        )
    return {
        "Descriptions": [creative.body],
        "FinalUrls": [creative.landing_url],
        "Headlines": [creative.title],
        "Status": write_status(ad.status),
    }


def ad_changes_to_ms(changes: dict) -> dict:
    """Map normalized ad update fields to a partial Bing Ad dict (status only)."""
    unsupported = [field for field in changes if field != "status"]
    if unsupported:
        raise ValidationError(
            "Microsoft Ads ad updates support only 'status' in this adapter — "
            f"create a new ad for content changes (got: {', '.join(sorted(unsupported))})."
        )
    if "status" not in changes:
        raise ValidationError("No supported ad fields to update.")
    return {"Status": status_to_ms(changes["status"])}


# ── Insights (Reporting service CSV) ──


def parse_report_csv(content: bytes, first_column: str) -> list[dict]:
    """Extract data rows from a Bing report download (a ZIP holding one CSV).

    Bing CSVs carry preamble lines (report name, time range, ...) before the
    column header row and a copyright footer after the data — everything
    before the row starting with ``first_column`` and after the first blank
    or ``©`` row is discarded.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if not names:
            return []
        text = archive.read(names[0]).decode("utf-8-sig")

    header: list[str] | None = None
    rows: list[dict] = []
    for row in csv.reader(io.StringIO(text)):
        if header is None:
            if row and row[0].strip() == first_column:
                header = [cell.strip() for cell in row]
            continue
        if not row or not row[0] or row[0].startswith("©"):
            break
        rows.append(dict(zip(header, (cell.strip() for cell in row), strict=False)))
    return rows


def _report_int(value: str | None) -> int | None:
    if value in (None, "", "--"):
        return None
    return int(float(value.replace(",", "")))


def _report_float(value: str | None) -> float | None:
    if value in (None, "", "--"):
        return None
    return float(value.replace(",", "").rstrip("%"))


def _report_decimal(value: str | None) -> Decimal | None:
    if value in (None, "", "--"):
        return None
    return Decimal(value.replace(",", ""))


def insights_from_report_row(
    row: dict,
    level: AdInsightsLevel,
    *,
    currency: str,
    id_column: str,
    fallback_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> AdInsights:
    """Map one Bing performance report CSV row to the universal AdInsights DTO.

    Ctr arrives as a percentage string ("5.00%") and is kept as a percent
    float; Spend/AverageCpc/Revenue are currency amounts in the account
    currency (labelled from the ``currency`` setting).
    """
    entity_id = row.get(id_column, "") if id_column else ""
    return AdInsights(
        level=level,
        entity_id=str(entity_id or fallback_id),
        date_start=since,
        date_stop=until,
        impressions=_report_int(row.get("Impressions")),
        clicks=_report_int(row.get("Clicks")),
        spend=_report_decimal(row.get("Spend")),
        currency=currency,
        ctr=_report_float(row.get("Ctr")),
        cpc=_report_decimal(row.get("AverageCpc")),
        conversions=_report_float(row.get("Conversions")),
        conversion_value=_report_decimal(row.get("Revenue")),
        extra={"raw": dict(row)},
    )
