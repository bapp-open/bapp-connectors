"""
Pinterest Ads <-> DTO mappers.

Converts between raw Pinterest API v5 payloads and normalized framework DTOs.
Pinterest budgets and bids are **micro-currency** integers (currency amount x
1,000,000), timestamps are unix seconds, and analytics rows are flat dicts
keyed by requested column names.

The ``*_to_pinterest_payload`` functions accept a plain dict of *normalized
DTO field names* (from ``dto.model_dump()`` or an update ``changes`` dict) so
the same mapper serves both create (full) and update (partial) flows.
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

MICRO_PER_UNIT = Decimal(1_000_000)

# ── Status maps ──

STATUS_FROM_PINTEREST = {
    "ACTIVE": AdEntityStatus.ACTIVE,
    "PAUSED": AdEntityStatus.PAUSED,
    "ARCHIVED": AdEntityStatus.ARCHIVED,
}

# Pinterest has no hard delete — entities are archived instead, so the
# normalized DELETED status writes as ARCHIVED.
STATUS_TO_PINTEREST = {
    AdEntityStatus.ACTIVE: "ACTIVE",
    AdEntityStatus.PAUSED: "PAUSED",
    AdEntityStatus.DELETED: "ARCHIVED",
    AdEntityStatus.ARCHIVED: "ARCHIVED",
}

# ── Objective maps ──

OBJECTIVE_FROM_PINTEREST = {
    "AWARENESS": AdObjective.AWARENESS,
    "CONSIDERATION": AdObjective.TRAFFIC,
    "VIDEO_VIEW": AdObjective.VIDEO_VIEWS,
    "WEB_CONVERSION": AdObjective.SALES,
    "CATALOG_SALES": AdObjective.SALES,
}

# Objectives Pinterest v5 has no native equivalent for fall back to
# CONSIDERATION (traffic-style delivery). The raw value is kept in extra.
OBJECTIVE_TO_PINTEREST = {
    AdObjective.AWARENESS: "AWARENESS",
    AdObjective.TRAFFIC: "CONSIDERATION",
    AdObjective.VIDEO_VIEWS: "VIDEO_VIEW",
    AdObjective.SALES: "WEB_CONVERSION",
    AdObjective.ENGAGEMENT: "CONSIDERATION",
    AdObjective.LEADS: "CONSIDERATION",
    AdObjective.APP_PROMOTION: "CONSIDERATION",
    AdObjective.OTHER: "CONSIDERATION",
}

# ── Age buckets ──

# Pinterest targets discrete age buckets; "65+" is open-ended.
AGE_BUCKETS: list[tuple[str, int, int | None]] = [
    ("18-24", 18, 24),
    ("25-34", 25, 34),
    ("35-44", 35, 44),
    ("45-49", 45, 49),
    ("50-54", 50, 54),
    ("55-64", 55, 64),
    ("65+", 65, None),
]

_BUCKET_BOUNDS = {name: (low, high) for name, low, high in AGE_BUCKETS}

_TARGETING_KEYS = {"GEO", "AGE_BUCKET", "GENDER"}


# ── Scalar helpers ──


def micro_to_decimal(value) -> Decimal | None:
    """Convert a Pinterest micro-currency amount (int) to a Decimal currency amount."""
    if value is None or value == "":
        return None
    return Decimal(str(value)) / MICRO_PER_UNIT


def decimal_to_micro(value) -> int:
    """Convert a Decimal currency amount to Pinterest micro-currency (int)."""
    return int((Decimal(str(value)) * MICRO_PER_UNIT).to_integral_value())


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _unix_to_datetime(value) -> datetime | None:
    """Parse a Pinterest unix-seconds timestamp into an aware UTC datetime."""
    if value is None or value == "":
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def _datetime_to_unix(value) -> int:
    """Serialize a DTO datetime (or an already-numeric value) to unix seconds."""
    if isinstance(value, datetime):
        return int(value.timestamp())
    return int(value)


def _parse_date(value) -> datetime | None:
    """Parse an analytics DATE column ("YYYY-MM-DD")."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        return None


# ── Status / objective helpers ──


def status_from_pinterest(value) -> AdEntityStatus:
    """Map a Pinterest entity status to AdEntityStatus (UNKNOWN when unrecognized)."""
    return STATUS_FROM_PINTEREST.get(str(value or ""), AdEntityStatus.UNKNOWN)


def status_to_pinterest(status) -> str:
    """Map a normalized status to Pinterest's ACTIVE/PAUSED/ARCHIVED.

    Pinterest cannot hard-delete, so DELETED writes as ARCHIVED.
    """
    value = STATUS_TO_PINTEREST.get(AdEntityStatus(status))
    if value is None:
        raise ValidationError(
            f"Pinterest Ads cannot set entity status '{status}' — use active, paused, deleted, or archived."
        )
    return value


def objective_from_pinterest(objective_type: str) -> AdObjective:
    return OBJECTIVE_FROM_PINTEREST.get(objective_type, AdObjective.OTHER)


def objective_to_pinterest(objective) -> str:
    return OBJECTIVE_TO_PINTEREST[AdObjective(objective)]


def _status_to_payload(data: dict, payload: dict) -> None:
    """Write a mapped status into a payload, skipping absent/UNKNOWN drafts."""
    status = data.get("status")
    if status is not None and AdEntityStatus(status) != AdEntityStatus.UNKNOWN:
        payload["status"] = status_to_pinterest(status)


# ── Age bucket helpers ──


def age_range_to_buckets(age_min: int | None, age_max: int | None) -> list[str]:
    """Map a normalized age range to the Pinterest age buckets that overlap it."""
    low = age_min if age_min is not None else 18
    return [
        name
        for name, bucket_low, bucket_high in AGE_BUCKETS
        if (age_max is None or bucket_low <= age_max) and (bucket_high is None or bucket_high >= low)
    ]


def age_buckets_to_range(buckets: list[str]) -> tuple[int | None, int | None]:
    """Map Pinterest age buckets back to (age_min, age_max).

    age_min is the lower bound of the first bucket, age_max the upper bound of
    the last; the open-ended "65+" bucket yields ``age_max=None``.
    """
    bounds = [_BUCKET_BOUNDS[bucket] for bucket in buckets if bucket in _BUCKET_BOUNDS]
    if not bounds:
        return None, None
    highs = [high for _, high in bounds]
    return min(low for low, _ in bounds), None if None in highs else max(highs)


# ── Targeting ──


def targeting_from_pinterest(spec: dict) -> AdTargeting:
    """Map a Pinterest targeting_spec to normalized AdTargeting."""
    spec = spec or {}
    age_min, age_max = age_buckets_to_range(spec.get("AGE_BUCKET") or [])
    genders = [str(gender).lower() for gender in spec.get("GENDER") or [] if str(gender).lower() in ("male", "female")]
    extra = {key: value for key, value in spec.items() if key not in _TARGETING_KEYS}
    return AdTargeting(
        countries=list(spec.get("GEO") or []),
        age_min=age_min,
        age_max=age_max,
        genders=genders,
        extra=extra,
    )


def targeting_to_pinterest(targeting) -> dict:
    """Build a Pinterest targeting_spec from normalized AdTargeting (or its dict dump)."""
    if isinstance(targeting, AdTargeting):
        targeting = targeting.model_dump()

    spec: dict = {}
    if targeting.get("countries"):
        spec["GEO"] = list(targeting["countries"])
    age_min = targeting.get("age_min")
    age_max = targeting.get("age_max")
    if age_min is not None or age_max is not None:
        spec["AGE_BUCKET"] = age_range_to_buckets(age_min, age_max)
    if targeting.get("genders"):
        spec["GENDER"] = [str(gender).lower() for gender in targeting["genders"]]
    spec.update(targeting.get("extra") or {})
    return spec


def _provider_meta(raw: dict, raw_id: str) -> ProviderMeta:
    return ProviderMeta(provider="pinterest", raw_id=raw_id, raw_payload=raw, fetched_at=datetime.now(UTC))


# ── Campaigns ──


def campaign_from_pinterest(raw: dict) -> AdCampaign:
    """Map a raw v5 campaign object to an AdCampaign DTO."""
    campaign_id = str(raw.get("id", ""))

    extra = {}
    if raw.get("objective_type"):
        extra["objective_type"] = raw["objective_type"]

    return AdCampaign(
        id=campaign_id,
        name=raw.get("name", ""),
        status=status_from_pinterest(raw.get("status")),
        objective=objective_from_pinterest(raw["objective_type"]) if raw.get("objective_type") else None,
        daily_budget=micro_to_decimal(raw.get("daily_spend_cap")),
        lifetime_budget=micro_to_decimal(raw.get("lifetime_spend_cap")),
        start_time=_unix_to_datetime(raw.get("start_time")),
        end_time=_unix_to_datetime(raw.get("end_time")),
        extra=extra,
        provider_meta=_provider_meta(raw, campaign_id),
    )


def campaign_to_pinterest_payload(data: dict) -> dict:
    """Build a campaign create/update payload from normalized fields.

    ``data`` uses AdCampaign field names (from ``model_dump()`` or an update
    changes dict); only present fields are written. ``ad_account_id`` is added
    by the client/adapter, and the caller wraps the payload in the list body
    Pinterest's bulk-style write endpoints expect.
    """
    payload: dict = {}
    if data.get("name") is not None:
        payload["name"] = data["name"]
    _status_to_payload(data, payload)
    if data.get("objective") is not None:
        payload["objective_type"] = objective_to_pinterest(data["objective"])
    if data.get("daily_budget") is not None:
        payload["daily_spend_cap"] = decimal_to_micro(data["daily_budget"])
    if data.get("lifetime_budget") is not None:
        payload["lifetime_spend_cap"] = decimal_to_micro(data["lifetime_budget"])
    if data.get("start_time") is not None:
        payload["start_time"] = _datetime_to_unix(data["start_time"])
    if data.get("end_time") is not None:
        payload["end_time"] = _datetime_to_unix(data["end_time"])
    return payload


# ── Ad groups ──


def ad_group_from_pinterest(raw: dict) -> AdGroup:
    """Map a raw v5 ad group object to an AdGroup DTO."""
    ad_group_id = str(raw.get("id", ""))

    budget = micro_to_decimal(raw.get("budget_in_micro_currency"))
    budget_type = str(raw.get("budget_type") or "")
    daily = budget if budget_type == "DAILY" else None
    lifetime = budget if budget_type == "LIFETIME" else None

    extra = {}
    if budget_type:
        extra["budget_type"] = budget_type

    return AdGroup(
        id=ad_group_id,
        campaign_id=str(raw.get("campaign_id", "")),
        name=raw.get("name", ""),
        status=status_from_pinterest(raw.get("status")),
        daily_budget=daily,
        lifetime_budget=lifetime,
        bid_amount=micro_to_decimal(raw.get("bid_in_micro_currency")),
        targeting=targeting_from_pinterest(raw.get("targeting_spec") or {}),
        start_time=_unix_to_datetime(raw.get("start_time")),
        end_time=_unix_to_datetime(raw.get("end_time")),
        extra=extra,
        provider_meta=_provider_meta(raw, ad_group_id),
    )


def ad_group_to_pinterest_payload(data: dict) -> dict:
    """Build an ad group create/update payload from normalized fields."""
    payload: dict = {}
    if data.get("name") is not None:
        payload["name"] = data["name"]
    if data.get("campaign_id"):
        payload["campaign_id"] = data["campaign_id"]
    _status_to_payload(data, payload)
    if data.get("daily_budget") is not None:
        payload["budget_in_micro_currency"] = decimal_to_micro(data["daily_budget"])
        payload["budget_type"] = "DAILY"
    elif data.get("lifetime_budget") is not None:
        payload["budget_in_micro_currency"] = decimal_to_micro(data["lifetime_budget"])
        payload["budget_type"] = "LIFETIME"
    if data.get("bid_amount") is not None:
        payload["bid_in_micro_currency"] = decimal_to_micro(data["bid_amount"])
    if data.get("start_time") is not None:
        payload["start_time"] = _datetime_to_unix(data["start_time"])
    if data.get("end_time") is not None:
        payload["end_time"] = _datetime_to_unix(data["end_time"])
    if data.get("targeting") is not None:
        payload["targeting_spec"] = targeting_to_pinterest(data["targeting"])
    return payload


# ── Ads ──


def ad_from_pinterest(raw: dict) -> Ad:
    """Map a raw v5 ad object to an Ad DTO.

    The promoted Pin's ID becomes ``creative.id``; the destination link (when
    present) becomes ``creative.landing_url``.
    """
    ad_id = str(raw.get("id", ""))

    creative = None
    if raw.get("pin_id"):
        creative = AdCreative(
            id=str(raw["pin_id"]),
            landing_url=raw.get("destination_url", "") or "",
        )

    extra = {}
    for key in ("creative_type", "pin_id"):
        if raw.get(key):
            extra[key] = raw[key]

    return Ad(
        id=ad_id,
        ad_group_id=str(raw.get("ad_group_id", "")),
        campaign_id=str(raw.get("campaign_id", "")),
        name=raw.get("name", ""),
        status=status_from_pinterest(raw.get("status")),
        creative=creative,
        extra=extra,
        provider_meta=_provider_meta(raw, ad_id),
    )


def ad_to_pinterest_payload(data: dict, *, for_create: bool = False) -> dict:
    """Build an ad create/update payload from normalized fields.

    A Pinterest ad promotes an existing Pin: the ``pin_id`` comes from
    ``ad.creative.id`` or ``ad.extra["pin_id"]`` and is required on create.
    """
    creative = data.get("creative") or {}
    if isinstance(creative, AdCreative):
        creative = creative.model_dump()

    payload: dict = {}
    if data.get("ad_group_id"):
        payload["ad_group_id"] = data["ad_group_id"]
    if data.get("name") is not None:
        payload["name"] = data["name"]
    _status_to_payload(data, payload)

    pin_id = creative.get("id") or (data.get("extra") or {}).get("pin_id")
    if pin_id:
        payload["pin_id"] = str(pin_id)
    elif for_create:
        raise ValidationError(
            "Pinterest ads promote an existing Pin — set Ad.creative.id (or extra['pin_id']) to the Pin's ID. "
            "Create the Pin first via the social/pinterest provider."
        )
    if for_create:
        payload["creative_type"] = "REGULAR"
    return payload


# ── Insights ──

_LEVEL_ID_COLUMNS = {
    AdInsightsLevel.ACCOUNT: "AD_ACCOUNT_ID",
    AdInsightsLevel.CAMPAIGN: "CAMPAIGN_ID",
    AdInsightsLevel.AD_GROUP: "AD_GROUP_ID",
    AdInsightsLevel.AD: "AD_ID",
}

_MAPPED_COLUMNS = {
    "IMPRESSION_1",
    "CLICKTHROUGH_1",
    "SPEND_IN_DOLLAR",
    "SPEND_IN_MICRO_DOLLAR",
    "CTR",
    "ECPC_IN_DOLLAR",
    "TOTAL_CONVERSIONS",
    "VIDEO_MRC_VIEWS_1",
    "DATE",
}


def level_id_column(level: AdInsightsLevel) -> str:
    """The analytics entity ID column for an insights level."""
    return _LEVEL_ID_COLUMNS[AdInsightsLevel(level)]


def insights_from_pinterest(row: dict, level: AdInsightsLevel) -> AdInsights:
    """Map one analytics row (flat dict keyed by column names) to AdInsights.

    Spend arrives as ``SPEND_IN_DOLLAR`` (currency units); rows carrying only
    ``SPEND_IN_MICRO_DOLLAR`` are tolerated and converted from micros.
    """
    level = AdInsightsLevel(level)
    id_column = level_id_column(level)

    spend = _to_decimal(row.get("SPEND_IN_DOLLAR"))
    if spend is None:
        spend = micro_to_decimal(row.get("SPEND_IN_MICRO_DOLLAR"))

    date = _parse_date(row.get("DATE"))
    extra = {
        key: value for key, value in row.items() if key not in _MAPPED_COLUMNS and key not in _LEVEL_ID_COLUMNS.values()
    }

    return AdInsights(
        level=level,
        entity_id=str(row.get(id_column, "") or ""),
        date_start=date,
        date_stop=date,
        impressions=_to_int(row.get("IMPRESSION_1")),
        clicks=_to_int(row.get("CLICKTHROUGH_1")),
        spend=spend,
        ctr=_to_float(row.get("CTR")),
        cpc=_to_decimal(row.get("ECPC_IN_DOLLAR")),
        conversions=_to_float(row.get("TOTAL_CONVERSIONS")),
        video_views=_to_int(row.get("VIDEO_MRC_VIEWS_1")),
        extra=extra,
    )
