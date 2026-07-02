"""
TikTok Ads <-> DTO mappers.

Converts between raw TikTok Business API payloads and normalized framework
DTOs. TikTok budgets and bids are plain currency floats (not cents), so
Decimal ↔ float conversion is lossless enough for ad budgets.

The ``*_to_tiktok_payload`` functions accept a plain dict of *normalized DTO
field names* (from ``dto.model_dump()`` or an update ``changes`` dict) so the
same mapper serves both create (full) and update (partial) flows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
    AdObjective,
    AdTargeting,
    ProviderMeta,
)
from bapp_connectors.core.errors import ValidationError

TIKTOK_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── Status maps ──

STATUS_FROM_TIKTOK = {
    "ENABLE": AdEntityStatus.ACTIVE,
    "DISABLE": AdEntityStatus.PAUSED,
    "DELETE": AdEntityStatus.DELETED,
}

STATUS_TO_TIKTOK = {
    AdEntityStatus.ACTIVE: "ENABLE",
    AdEntityStatus.PAUSED: "DISABLE",
    AdEntityStatus.DELETED: "DELETE",
}

# ── Objective maps ──

OBJECTIVE_TO_TIKTOK = {
    AdObjective.AWARENESS: "REACH",
    AdObjective.TRAFFIC: "TRAFFIC",
    AdObjective.ENGAGEMENT: "ENGAGEMENT",
    AdObjective.LEADS: "LEAD_GENERATION",
    AdObjective.APP_PROMOTION: "APP_PROMOTION",
    AdObjective.SALES: "PRODUCT_SALES",
    AdObjective.VIDEO_VIEWS: "VIDEO_VIEWS",
    AdObjective.OTHER: "TRAFFIC",
}

OBJECTIVE_FROM_TIKTOK = {
    "REACH": AdObjective.AWARENESS,
    "TRAFFIC": AdObjective.TRAFFIC,
    "ENGAGEMENT": AdObjective.ENGAGEMENT,
    "LEAD_GENERATION": AdObjective.LEADS,
    "APP_PROMOTION": AdObjective.APP_PROMOTION,
    "PRODUCT_SALES": AdObjective.SALES,
    "VIDEO_VIEWS": AdObjective.VIDEO_VIEWS,
    "CONVERSIONS": AdObjective.SALES,
    "RF_REACH": AdObjective.AWARENESS,
}

# ── Age brackets ──

AGE_BRACKETS: list[tuple[str, int, int]] = [
    ("AGE_13_17", 13, 17),
    ("AGE_18_24", 18, 24),
    ("AGE_25_34", 25, 34),
    ("AGE_35_44", 35, 44),
    ("AGE_45_54", 45, 54),
    ("AGE_55_100", 55, 100),
]

_BRACKET_BOUNDS = {name: (low, high) for name, low, high in AGE_BRACKETS}


# ── Scalar helpers ──


def to_decimal(value) -> Decimal | None:
    """Convert a TikTok currency amount (float or string) to Decimal."""
    if value is None or value == "":
        return None
    return Decimal(str(value))


def decimal_to_float(value) -> float | None:
    """Convert a DTO Decimal budget/bid to TikTok's plain currency float."""
    if value is None:
        return None
    return float(value)


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _parse_datetime(value) -> datetime | None:
    """Parse a TikTok "YYYY-MM-DD HH:MM:SS" timestamp."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIKTOK_DATETIME_FORMAT)
    except ValueError:
        return None


def _format_datetime(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime(TIKTOK_DATETIME_FORMAT)


# ── Status / objective helpers ──


def status_from_tiktok(raw: dict) -> AdEntityStatus:
    """Map TikTok operation_status (+ secondary_status hints) to AdEntityStatus."""
    secondary = str(raw.get("secondary_status") or "")
    if "REJECT" in secondary:
        return AdEntityStatus.REJECTED
    if "AUDIT" in secondary:
        return AdEntityStatus.PENDING_REVIEW
    return STATUS_FROM_TIKTOK.get(str(raw.get("operation_status") or ""), AdEntityStatus.UNKNOWN)


def status_to_tiktok(status: AdEntityStatus) -> str:
    """Map a normalized status to TikTok's ENABLE/DISABLE/DELETE operation."""
    operation = STATUS_TO_TIKTOK.get(AdEntityStatus(status))
    if operation is None:
        raise ValidationError(f"TikTok Ads cannot set entity status '{status}' — use active, paused, or deleted.")
    return operation


def objective_from_tiktok(objective_type: str) -> AdObjective:
    return OBJECTIVE_FROM_TIKTOK.get(objective_type, AdObjective.OTHER)


def objective_to_tiktok(objective) -> str:
    return OBJECTIVE_TO_TIKTOK[AdObjective(objective)]


# ── Age bracket helpers ──


def age_range_to_groups(age_min: int | None, age_max: int | None) -> list[str]:
    """Map a normalized age range to the TikTok brackets that overlap it."""
    low = age_min if age_min is not None else 13
    high = age_max if age_max is not None else 100
    return [name for name, bracket_low, bracket_high in AGE_BRACKETS if bracket_low <= high and bracket_high >= low]


def age_groups_to_range(age_groups: list[str]) -> tuple[int | None, int | None]:
    """Map TikTok age brackets back to (age_min, age_max) — min of the first bracket, max of the last."""
    bounds = [_BRACKET_BOUNDS[group] for group in age_groups if group in _BRACKET_BOUNDS]
    if not bounds:
        return None, None
    return min(low for low, _ in bounds), max(high for _, high in bounds)


# ── Budget helpers ──


def _budget_from_tiktok(raw: dict) -> tuple[Decimal | None, Decimal | None]:
    """Split TikTok budget_mode + budget into (daily_budget, lifetime_budget)."""
    budget = to_decimal(raw.get("budget"))
    mode = raw.get("budget_mode", "")
    if mode == "BUDGET_MODE_DAY":
        return budget, None
    if mode == "BUDGET_MODE_TOTAL":
        return None, budget
    return None, None


def _budget_to_tiktok(data: dict, payload: dict, partial: bool) -> None:
    """Write budget_mode + budget into a TikTok payload from normalized fields."""
    daily = data.get("daily_budget")
    lifetime = data.get("lifetime_budget")
    if daily is not None:
        payload["budget_mode"] = "BUDGET_MODE_DAY"
        payload["budget"] = decimal_to_float(daily)
    elif lifetime is not None:
        payload["budget_mode"] = "BUDGET_MODE_TOTAL"
        payload["budget"] = decimal_to_float(lifetime)
    elif not partial:
        payload["budget_mode"] = "BUDGET_MODE_INFINITE"


def _provider_meta(raw: dict, raw_id: str) -> ProviderMeta:
    return ProviderMeta(provider="tiktok", raw_id=raw_id, raw_payload=raw, fetched_at=datetime.now(UTC))


# ── Campaigns ──


def campaign_from_tiktok(raw: dict) -> AdCampaign:
    """Map a raw campaign/get/ row to an AdCampaign DTO."""
    campaign_id = str(raw.get("campaign_id", ""))
    daily, lifetime = _budget_from_tiktok(raw)

    extra = {}
    for key in ("create_time", "modify_time"):
        if raw.get(key):
            extra[key] = raw[key]

    return AdCampaign(
        id=campaign_id,
        name=raw.get("campaign_name", ""),
        status=status_from_tiktok(raw),
        objective=objective_from_tiktok(raw.get("objective_type", "")) if raw.get("objective_type") else None,
        daily_budget=daily,
        lifetime_budget=lifetime,
        extra=extra,
        provider_meta=_provider_meta(raw, campaign_id),
    )


def campaign_to_tiktok_payload(data: dict, *, partial: bool = False) -> dict:
    """Build a campaign/create/ or campaign/update/ payload from normalized fields.

    ``data`` uses AdCampaign field names (from ``model_dump()`` or an update
    changes dict). With ``partial=True`` only present fields are written and no
    BUDGET_MODE_INFINITE default is applied.
    """
    payload: dict = {}
    if data.get("name") is not None:
        payload["campaign_name"] = data["name"]
    if data.get("objective") is not None:
        payload["objective_type"] = objective_to_tiktok(data["objective"])
    _budget_to_tiktok(data, payload, partial)
    return payload


# ── Ad groups ──


def _targeting_from_tiktok(raw: dict) -> AdTargeting:
    age_min, age_max = age_groups_to_range(raw.get("age_groups") or [])
    genders = {
        "GENDER_MALE": ["male"],
        "GENDER_FEMALE": ["female"],
    }.get(str(raw.get("gender") or ""), [])

    # TikTok location_ids are numeric platform IDs, not ISO country codes,
    # so they are preserved in extra instead of the normalized countries list.
    extra = {}
    if raw.get("location_ids"):
        extra["location_ids"] = raw["location_ids"]

    return AdTargeting(age_min=age_min, age_max=age_max, genders=genders, extra=extra)


def _targeting_to_tiktok(targeting, payload: dict) -> None:
    if isinstance(targeting, AdTargeting):
        targeting = targeting.model_dump()

    age_min = targeting.get("age_min")
    age_max = targeting.get("age_max")
    if age_min is not None or age_max is not None:
        payload["age_groups"] = age_range_to_groups(age_min, age_max)

    genders = [gender.lower() for gender in targeting.get("genders") or []]
    if genders == ["male"]:
        payload["gender"] = "GENDER_MALE"
    elif genders == ["female"]:
        payload["gender"] = "GENDER_FEMALE"
    elif genders:
        payload["gender"] = "GENDER_UNLIMITED"

    extra = targeting.get("extra") or {}
    if extra.get("location_ids"):
        payload["location_ids"] = extra["location_ids"]
    elif targeting.get("countries"):
        # TikTok expects numeric location IDs, not ISO country codes — pass the
        # ISO list through so callers can resolve it (tool/region/get/) upstream.
        payload["countries"] = targeting["countries"]


def ad_group_from_tiktok(raw: dict) -> AdGroup:
    """Map a raw adgroup/get/ row to an AdGroup DTO."""
    adgroup_id = str(raw.get("adgroup_id", ""))
    daily, lifetime = _budget_from_tiktok(raw)

    extra = {}
    for key in ("create_time", "modify_time"):
        if raw.get(key):
            extra[key] = raw[key]

    return AdGroup(
        id=adgroup_id,
        campaign_id=str(raw.get("campaign_id", "")),
        name=raw.get("adgroup_name", ""),
        status=status_from_tiktok(raw),
        daily_budget=daily,
        lifetime_budget=lifetime,
        bid_amount=to_decimal(raw.get("bid_price")),
        targeting=_targeting_from_tiktok(raw),
        start_time=_parse_datetime(raw.get("schedule_start_time")),
        end_time=_parse_datetime(raw.get("schedule_end_time")),
        extra=extra,
        provider_meta=_provider_meta(raw, adgroup_id),
    )


def ad_group_to_tiktok_payload(data: dict, *, partial: bool = False) -> dict:
    """Build an adgroup/create/ or adgroup/update/ payload from normalized fields."""
    payload: dict = {}
    if data.get("name") is not None:
        payload["adgroup_name"] = data["name"]
    if data.get("campaign_id"):
        payload["campaign_id"] = data["campaign_id"]
    _budget_to_tiktok(data, payload, partial)
    if data.get("bid_amount") is not None:
        payload["bid_price"] = decimal_to_float(data["bid_amount"])
    if data.get("start_time") is not None:
        payload["schedule_start_time"] = _format_datetime(data["start_time"])
    if data.get("end_time") is not None:
        payload["schedule_end_time"] = _format_datetime(data["end_time"])
    if data.get("targeting") is not None:
        _targeting_to_tiktok(data["targeting"], payload)
    return payload


# ── Ads ──


def ad_from_tiktok(raw: dict) -> Ad:
    """Map a raw ad/get/ row to an Ad DTO."""
    ad_id = str(raw.get("ad_id", ""))

    creative = AdCreative(
        body=raw.get("ad_text", "") or "",
        landing_url=raw.get("landing_page_url", "") or "",
        call_to_action=raw.get("call_to_action", "") or "",
        thumbnail_url=raw.get("video_cover_url", "") or "",
    )

    extra = {}
    for key in ("video_id", "image_ids", "identity_id", "identity_type"):
        if raw.get(key):
            extra[key] = raw[key]

    return Ad(
        id=ad_id,
        ad_group_id=str(raw.get("adgroup_id", "")),
        campaign_id=str(raw.get("campaign_id", "")),
        name=raw.get("ad_name", ""),
        status=status_from_tiktok(raw),
        creative=creative,
        extra=extra,
        provider_meta=_provider_meta(raw, ad_id),
    )


def ad_creative_to_tiktok(data: dict) -> dict:
    """Build one TikTok creative dict from normalized Ad fields.

    Used inside the ``creatives`` list of ad/create/ and ad/update/ payloads.
    ``video_id``/``image_ids`` and ``identity_id``/``identity_type`` pass
    through from ``Ad.extra``, falling back to ``Ad.creative.extra`` (where
    CreativeUploadCapability.create_creative merges uploaded media references).
    """
    creative = data.get("creative") or {}
    if isinstance(creative, AdCreative):
        creative = creative.model_dump()

    payload: dict = {}
    if data.get("name"):
        payload["ad_name"] = data["name"]
    if creative.get("body"):
        payload["ad_text"] = creative["body"]
    if creative.get("call_to_action"):
        payload["call_to_action"] = creative["call_to_action"]
    if creative.get("landing_url"):
        payload["landing_page_url"] = creative["landing_url"]

    extra = data.get("extra") or {}
    creative_extra = creative.get("extra") or {}
    for key in ("video_id", "image_ids", "identity_id", "identity_type"):
        if key in extra:
            payload[key] = extra[key]
        elif key in creative_extra:
            payload[key] = creative_extra[key]
    return payload


def ad_to_tiktok_payload(data: dict) -> dict:
    """Build an ad/create/ payload: adgroup_id + a single-creative list."""
    return {
        "adgroup_id": data.get("ad_group_id", ""),
        "creatives": [ad_creative_to_tiktok(data)],
    }


# ── Insights ──

_LEVEL_ID_DIMENSIONS = {
    AdInsightsLevel.ACCOUNT: "advertiser_id",
    AdInsightsLevel.CAMPAIGN: "campaign_id",
    AdInsightsLevel.AD_GROUP: "adgroup_id",
    AdInsightsLevel.AD: "ad_id",
}

_MAPPED_METRICS = {
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "reach",
    "frequency",
    "conversion",
    "video_play_actions",
}


def level_id_dimension(level: AdInsightsLevel) -> str:
    """The TikTok report ID dimension for an insights level."""
    return _LEVEL_ID_DIMENSIONS[AdInsightsLevel(level)]


def insights_from_tiktok(row: dict, level: AdInsightsLevel) -> AdInsights:
    """Map a report/integrated/get/ row to the universal AdInsights DTO."""
    dimensions = row.get("dimensions", {}) or {}
    metrics = row.get("metrics", {}) or {}

    stat_day = _parse_datetime(dimensions.get("stat_time_day"))
    extra = {key: value for key, value in metrics.items() if key not in _MAPPED_METRICS}

    return AdInsights(
        level=AdInsightsLevel(level),
        entity_id=str(dimensions.get(level_id_dimension(level), "")),
        date_start=stat_day,
        date_stop=stat_day,
        impressions=_to_int(metrics.get("impressions")),
        clicks=_to_int(metrics.get("clicks")),
        spend=to_decimal(metrics.get("spend")),
        ctr=_to_float(metrics.get("ctr")),
        cpc=to_decimal(metrics.get("cpc")),
        cpm=to_decimal(metrics.get("cpm")),
        reach=_to_int(metrics.get("reach")),
        frequency=_to_float(metrics.get("frequency")),
        conversions=_to_float(metrics.get("conversion")),
        video_views=_to_int(metrics.get("video_play_actions")),
        extra=extra,
    )
