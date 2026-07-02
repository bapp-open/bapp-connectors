"""
Meta Marketing API <-> DTO mappers.

Converts between raw Graph API payloads and normalized framework DTOs.

Money: Meta budgets and bid amounts are minor currency units (cents) serialized
as strings; insights ``spend``/``cpc``/``cpm`` are in currency units.
"""

from __future__ import annotations

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
    AdTargeting,
)
from bapp_connectors.core.errors import ValidationError

# ── Money helpers ──


def _minor_to_decimal(value) -> Decimal | None:
    """Convert Meta minor units (cents, as str/int) to a Decimal in currency units."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)) / 100
    except InvalidOperation:
        return None


def _decimal_to_minor(value) -> str:
    """Convert a Decimal (or numeric) in currency units to Meta minor units (cents, as str)."""
    return str(int(Decimal(str(value)) * 100))


# ── Status maps ──

STATUS_TO_META: dict[AdEntityStatus, str] = {
    AdEntityStatus.ACTIVE: "ACTIVE",
    AdEntityStatus.PAUSED: "PAUSED",
    AdEntityStatus.DELETED: "DELETED",
    AdEntityStatus.ARCHIVED: "ARCHIVED",
}

META_TO_STATUS: dict[str, AdEntityStatus] = {meta: status for status, meta in STATUS_TO_META.items()}

# effective_status carries review/delivery states beyond the configured status.
META_EFFECTIVE_TO_STATUS: dict[str, AdEntityStatus] = {
    **META_TO_STATUS,
    "PENDING_REVIEW": AdEntityStatus.PENDING_REVIEW,
    "DISAPPROVED": AdEntityStatus.REJECTED,
    "WITH_ISSUES": AdEntityStatus.REJECTED,
    "CAMPAIGN_PAUSED": AdEntityStatus.PAUSED,
    "ADSET_PAUSED": AdEntityStatus.PAUSED,
}


def status_from_meta(data: dict) -> AdEntityStatus:
    """Derive the normalized status, preferring effective_status when present."""
    effective = data.get("effective_status")
    if effective:
        return META_EFFECTIVE_TO_STATUS.get(effective, AdEntityStatus.UNKNOWN)
    status = data.get("status")
    if status:
        return META_TO_STATUS.get(status, AdEntityStatus.UNKNOWN)
    return AdEntityStatus.UNKNOWN


# ── Objective maps ──

OBJECTIVE_TO_META: dict[AdObjective, str] = {
    AdObjective.AWARENESS: "OUTCOME_AWARENESS",
    AdObjective.TRAFFIC: "OUTCOME_TRAFFIC",
    AdObjective.ENGAGEMENT: "OUTCOME_ENGAGEMENT",
    AdObjective.LEADS: "OUTCOME_LEADS",
    AdObjective.APP_PROMOTION: "OUTCOME_APP_PROMOTION",
    AdObjective.SALES: "OUTCOME_SALES",
    AdObjective.VIDEO_VIEWS: "OUTCOME_ENGAGEMENT",
    AdObjective.OTHER: "OUTCOME_TRAFFIC",
}

META_TO_OBJECTIVE: dict[str, AdObjective] = {}
for _objective, _meta in OBJECTIVE_TO_META.items():
    META_TO_OBJECTIVE.setdefault(_meta, _objective)
# Legacy (pre-OUTCOME) objectives still returned for old campaigns.
META_TO_OBJECTIVE.update(
    {
        "LINK_CLICKS": AdObjective.TRAFFIC,
        "CONVERSIONS": AdObjective.SALES,
        "VIDEO_VIEWS": AdObjective.VIDEO_VIEWS,
    }
)


def objective_from_meta(value: str) -> AdObjective:
    """Map a Meta objective (OUTCOME_* or legacy) to the normalized objective."""
    return META_TO_OBJECTIVE.get(value, AdObjective.OTHER)


# ── Shared helpers ──


def _parse_datetime(value) -> datetime | None:
    """Parse a Graph API timestamp (ISO 8601, e.g. '2026-01-01T00:00:00+0000')."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _to_iso(value) -> str:
    """Serialize a datetime (or pass through a string) for a Graph API payload."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _as_dict(entity) -> dict:
    """Normalize a DTO or a partial-changes dict to a plain dict of set fields."""
    if isinstance(entity, dict):
        return entity
    return entity.model_dump(exclude_none=True)


def _status_payload_value(data: dict, for_create: bool) -> str | None:
    """Resolve the Meta status for a payload; new entities default to PAUSED."""
    status = data.get("status")
    mapped = STATUS_TO_META.get(AdEntityStatus(status)) if status else None
    if mapped:
        return mapped
    if for_create:
        return "PAUSED"
    return None


# ── Campaigns ──


def campaign_from_meta(data: dict) -> AdCampaign:
    """Map a raw Marketing API campaign to the AdCampaign DTO."""
    return AdCampaign(
        id=str(data.get("id", "")),
        name=data.get("name", ""),
        status=status_from_meta(data),
        objective=objective_from_meta(data["objective"]) if data.get("objective") else None,
        daily_budget=_minor_to_decimal(data.get("daily_budget")),
        lifetime_budget=_minor_to_decimal(data.get("lifetime_budget")),
        start_time=_parse_datetime(data.get("start_time")),
        end_time=_parse_datetime(data.get("stop_time")),
    )


def campaign_to_meta_payload(campaign: AdCampaign | dict, for_create: bool = False) -> dict:
    """Build a Marketing API campaign payload from a DTO or a partial-changes dict."""
    data = _as_dict(campaign)
    payload: dict = {}
    if "name" in data:
        payload["name"] = data["name"]
    if data.get("objective"):
        payload["objective"] = OBJECTIVE_TO_META[AdObjective(data["objective"])]
    if status := _status_payload_value(data, for_create):
        payload["status"] = status
    if data.get("daily_budget") is not None:
        payload["daily_budget"] = _decimal_to_minor(data["daily_budget"])
    if data.get("lifetime_budget") is not None:
        payload["lifetime_budget"] = _decimal_to_minor(data["lifetime_budget"])
    if data.get("start_time"):
        payload["start_time"] = _to_iso(data["start_time"])
    if data.get("end_time"):
        payload["stop_time"] = _to_iso(data["end_time"])
    if for_create:
        payload["special_ad_categories"] = []
    return payload


# ── Targeting ──

_GENDER_TO_META = {"male": 1, "female": 2}
_META_TO_GENDER = {1: "male", 2: "female"}
_TARGETING_KEYS = {"geo_locations", "age_min", "age_max", "genders"}


def targeting_to_meta(targeting: AdTargeting) -> dict:
    """Build a Marketing API targeting spec from the normalized AdTargeting."""
    spec: dict = {}
    if targeting.countries:
        spec["geo_locations"] = {"countries": list(targeting.countries)}
    if targeting.age_min is not None:
        spec["age_min"] = targeting.age_min
    if targeting.age_max is not None:
        spec["age_max"] = targeting.age_max
    if targeting.genders:
        spec["genders"] = [_GENDER_TO_META[g] for g in targeting.genders if g in _GENDER_TO_META]
    if targeting.extra:
        spec.update(targeting.extra)
    return spec


def targeting_from_meta(spec: dict) -> AdTargeting:
    """Map a Marketing API targeting spec to the normalized AdTargeting."""
    geo = spec.get("geo_locations") or {}
    genders = [_META_TO_GENDER[g] for g in spec.get("genders", []) if g in _META_TO_GENDER]
    extra = {key: value for key, value in spec.items() if key not in _TARGETING_KEYS}
    return AdTargeting(
        countries=list(geo.get("countries", [])),
        age_min=spec.get("age_min"),
        age_max=spec.get("age_max"),
        genders=genders,
        extra=extra,
    )


# ── Ad groups (Meta ad sets) ──


def ad_group_from_meta(data: dict) -> AdGroup:
    """Map a raw Marketing API ad set to the AdGroup DTO."""
    targeting = targeting_from_meta(data["targeting"]) if data.get("targeting") else None
    return AdGroup(
        id=str(data.get("id", "")),
        campaign_id=str(data.get("campaign_id", "")),
        name=data.get("name", ""),
        status=status_from_meta(data),
        daily_budget=_minor_to_decimal(data.get("daily_budget")),
        lifetime_budget=_minor_to_decimal(data.get("lifetime_budget")),
        bid_amount=_minor_to_decimal(data.get("bid_amount")),
        targeting=targeting,
        start_time=_parse_datetime(data.get("start_time")),
        end_time=_parse_datetime(data.get("end_time")),
    )


def ad_group_to_meta_payload(
    ad_group: AdGroup | dict,
    for_create: bool = False,
    billing_event: str | None = None,
    optimization_goal: str | None = None,
) -> dict:
    """Build a Marketing API ad set payload from a DTO or a partial-changes dict.

    ``billing_event`` and ``optimization_goal`` (from adapter config) are only
    applied on create.
    """
    data = _as_dict(ad_group)
    payload: dict = {}
    if data.get("campaign_id"):
        payload["campaign_id"] = data["campaign_id"]
    if "name" in data:
        payload["name"] = data["name"]
    if status := _status_payload_value(data, for_create):
        payload["status"] = status
    if data.get("daily_budget") is not None:
        payload["daily_budget"] = _decimal_to_minor(data["daily_budget"])
    if data.get("lifetime_budget") is not None:
        payload["lifetime_budget"] = _decimal_to_minor(data["lifetime_budget"])
    if data.get("bid_amount") is not None:
        payload["bid_amount"] = _decimal_to_minor(data["bid_amount"])
    if data.get("targeting") is not None:
        targeting = data["targeting"]
        if isinstance(targeting, dict):
            targeting = AdTargeting.model_validate(targeting)
        payload["targeting"] = targeting_to_meta(targeting)
    if data.get("start_time"):
        payload["start_time"] = _to_iso(data["start_time"])
    if data.get("end_time"):
        payload["end_time"] = _to_iso(data["end_time"])
    if for_create:
        if billing_event:
            payload["billing_event"] = billing_event
        if optimization_goal:
            payload["optimization_goal"] = optimization_goal
    return payload


# ── Ads ──


def ad_from_meta(data: dict) -> Ad:
    """Map a raw Marketing API ad to the Ad DTO."""
    creative = None
    if raw_creative := data.get("creative"):
        known = {"id", "title", "body", "image_url", "thumbnail_url"}
        creative = AdCreative(
            id=str(raw_creative.get("id", "")),
            title=raw_creative.get("title", ""),
            body=raw_creative.get("body", ""),
            media_url=raw_creative.get("image_url", ""),
            thumbnail_url=raw_creative.get("thumbnail_url", ""),
            extra={key: value for key, value in raw_creative.items() if key not in known},
        )
    return Ad(
        id=str(data.get("id", "")),
        ad_group_id=str(data.get("adset_id", "")),
        campaign_id=str(data.get("campaign_id", "")),
        name=data.get("name", ""),
        status=status_from_meta(data),
        creative=creative,
    )


def ad_to_meta_payload(ad: Ad | dict, for_create: bool = False) -> dict:
    """Build a Marketing API ad payload from a DTO or a partial-changes dict.

    Creating an ad requires either an existing creative ID (``creative.id``) or
    a raw ``object_story_spec`` in ``ad.extra``.
    """
    data = _as_dict(ad)
    payload: dict = {}
    if "name" in data:
        payload["name"] = data["name"]
    if data.get("ad_group_id"):
        payload["adset_id"] = data["ad_group_id"]
    if status := _status_payload_value(data, for_create):
        payload["status"] = status

    creative = data.get("creative") or {}
    extra = data.get("extra") or {}
    if creative.get("id"):
        payload["creative"] = {"creative_id": creative["id"]}
    elif extra.get("object_story_spec"):
        payload["creative"] = {"object_story_spec": extra["object_story_spec"]}
    elif for_create:
        raise ValidationError(
            "Meta ads require a creative: set creative.id to an existing creative ID "
            "or provide extra['object_story_spec']."
        )
    return payload


# ── Insights ──

_LEVEL_ID_KEYS: dict[AdInsightsLevel, str] = {
    AdInsightsLevel.ACCOUNT: "account_id",
    AdInsightsLevel.CAMPAIGN: "campaign_id",
    AdInsightsLevel.AD_GROUP: "adset_id",
    AdInsightsLevel.AD: "ad_id",
}


def _is_conversion(action_type: str) -> bool:
    return "purchase" in action_type or "offsite_conversion" in action_type


def _sum_actions(entries: list[dict] | None, matcher) -> float | None:
    """Sum matching action values. None when no entries match (or the list is absent)."""
    if not entries:
        return None
    total = 0.0
    matched = False
    for entry in entries:
        if matcher(entry.get("action_type", "")):
            total += float(entry.get("value", 0))
            matched = True
    return total if matched else None


def insights_from_meta(row: dict, level: AdInsightsLevel) -> AdInsights:
    """Map one Marketing API insights row to the universal AdInsights DTO.

    Meta reports ``spend``/``cpc``/``cpm`` in currency units (not cents).
    """
    conversions = _sum_actions(row.get("actions"), _is_conversion)

    conversion_value = None
    if (raw_value := _sum_actions(row.get("action_values"), _is_conversion)) is not None:
        conversion_value = Decimal(str(raw_value))

    video_views = _sum_actions(row.get("video_play_actions"), lambda _at: True)
    if video_views is None:
        video_views = _sum_actions(row.get("actions"), lambda at: at == "video_view")

    return AdInsights(
        level=level,
        entity_id=str(row.get(_LEVEL_ID_KEYS[level], "")),
        date_start=_parse_datetime(row.get("date_start")),
        date_stop=_parse_datetime(row.get("date_stop")),
        impressions=int(row["impressions"]) if row.get("impressions") is not None else None,
        clicks=int(row["clicks"]) if row.get("clicks") is not None else None,
        spend=Decimal(str(row["spend"])) if row.get("spend") is not None else None,
        currency=row.get("account_currency", ""),
        ctr=float(row["ctr"]) if row.get("ctr") is not None else None,
        cpc=Decimal(str(row["cpc"])) if row.get("cpc") is not None else None,
        cpm=Decimal(str(row["cpm"])) if row.get("cpm") is not None else None,
        reach=int(row["reach"]) if row.get("reach") is not None else None,
        frequency=float(row["frequency"]) if row.get("frequency") is not None else None,
        conversions=conversions,
        conversion_value=conversion_value,
        video_views=int(video_views) if video_views is not None else None,
    )
