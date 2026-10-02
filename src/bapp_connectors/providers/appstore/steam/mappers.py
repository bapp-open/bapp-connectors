"""Conversii Steamworks <-> DTO-uri."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from bapp_connectors.core.dto import (
    AppStoreApp,
    AppStorePlatform,
    AppStoreProductType,
    AppStoreRefund,
    AppStoreReview,
    AppStoreSale,
    FinancialTransaction,
    FinancialTransactionType,
    ProviderMeta,
)
from bapp_connectors.core.reports import stable_key, to_decimal

PROVIDER = "steam"
CURRENCY = "USD"
REVENUE_SHARE = Decimal("0.30")
BONUS_TIERS = {0: Decimal("0"), 1: Decimal("0.05"), 2: Decimal("0.10")}
CENT = Decimal("0.01")

#: line_item_type: documentat ca intreg (1 = pachet, 2 = DLC, 3 = microtranzactie), in realitate vine ca text ("Package")
LINE_ITEM_TYPES = {1: AppStoreProductType.APP, 2: AppStoreProductType.DLC, 3: AppStoreProductType.IAP}
LINE_ITEM_TYPE_NAMES = {
    "package": AppStoreProductType.APP,
    "bundle": AppStoreProductType.APP,
    "dlc": AppStoreProductType.DLC,
    "in-game item": AppStoreProductType.IAP,
    "microtransaction": AppStoreProductType.IAP,
}


def _meta(raw: dict, raw_id: str = "") -> ProviderMeta:
    return ProviderMeta(provider=PROVIDER, raw_id=raw_id, raw_payload=raw, fetched_at=datetime.now(UTC))


def _names(payload: dict, key: str, id_key: str, name_key: str) -> dict[str, str]:
    return {str(item.get(id_key)): item.get(name_key) or item.get("name", "") for item in payload.get(key, []) or []}


def _int(row: dict, key: str) -> int:
    return int(row.get(key) or 0)


_MONEY_FIELDS = ("gross_sales_usd", "gross_returns_usd", "net_tax_usd", "net_sales_usd")


def _has_activity(row: dict) -> bool:
    """Se sare doar randul fara unitati SI fara bani (activarile de chei Retail).

    Un rand cu 0 unitati poate purta totusi o corectie de taxa sau de vanzare neta; acela ramane.
    """
    # unitatile pot fi negative (retururi): conteaza orice valoare != 0
    if _int(row, "gross_units_sold") != 0 or _int(row, "gross_units_returned") != 0:
        return True
    return any(_money(row.get(field) or 0) for field in _MONEY_FIELDS)


def _app_id(row: dict) -> str:
    return str(row.get("primary_appid") or row.get("appid") or "")


def _product_type(row: dict) -> AppStoreProductType:
    if _int(row, "bundleid"):
        return AppStoreProductType.APP
    value = row.get("line_item_type")
    try:
        return LINE_ITEM_TYPES.get(int(value), AppStoreProductType.OTHER)
    except (TypeError, ValueError):
        return LINE_ITEM_TYPE_NAMES.get(str(value).strip().lower(), AppStoreProductType.OTHER)


def _money(value) -> Decimal:
    return to_decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _row_key(row: dict, day: date) -> str:
    return stable_key(PROVIDER, day, *(row.get(k) for k in ("line_item_type", "packageid", "bundleid", "appid", "primary_appid", "game_item_id", "package_sale_type", "key_request_id", "platform", "country_code", "base_price", "sale_price")))


def _at(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def sales_from_detailed(payload: dict, day: date) -> list[AppStoreSale]:
    apps = _names(payload, "app_info", "appid", "app_name")
    packages = _names(payload, "package_info", "packageid", "package_name")
    sales = []
    for row in payload.get("results", []) or []:
        if not _has_activity(row):
            continue
        key = _row_key(row, day)
        product_type = _product_type(row)
        app_id = _app_id(row)
        net_units = Decimal(_int(row, "net_units_sold"))
        sales.append(
            AppStoreSale(
                external_key=key,
                period_start=day,
                period_end=day,
                app_id=app_id,
                sku=str(row.get("packageid") or row.get("bundleid") or row.get("game_item_id") or ""),
                product_name=packages.get(str(row.get("packageid")), "") or apps.get(app_id, ""),
                product_type=product_type,
                units=net_units,
                country=row.get("country_code", ""),
                customer_currency=row.get("currency", "") or "",
                customer_price=(to_decimal(str(row.get("sale_price") or 0)) / 100).quantize(CENT, rounding=ROUND_HALF_UP),
                proceeds_currency=CURRENCY,
                proceeds_unit=(_money(row.get("net_sales_usd", 0)) / net_units).quantize(CENT) if net_units else Decimal("0"),
                proceeds_total=_money(row.get("net_sales_usd", 0)),
                is_refund=_int(row, "gross_units_sold") == 0 and _int(row, "gross_units_returned") != 0,
                extra={
                    "gross_units_sold": _int(row, "gross_units_sold"),
                    "gross_units_returned": _int(row, "gross_units_returned"),
                    "gross_units_activated": _int(row, "gross_units_activated"),
                    "package_sale_type": row.get("package_sale_type", ""),
                    "base_price": str(row.get("base_price") or ""),
                    "sale_price": str(row.get("sale_price") or ""),
                    "currency": row.get("currency", "") or "",
                    "gross_sales_usd": str(_money(row.get("gross_sales_usd") or 0)),
                    "gross_returns_usd": str(_money(row.get("gross_returns_usd", 0))),
                    "net_tax_usd": str(_money(row.get("net_tax_usd", 0))),
                    "platform": row.get("platform", ""),
                    "app_name": apps.get(app_id, ""),
                    "revenue_share_tier": _int(row, "additional_revenue_share_tier"),
                },
                provider_meta=_meta(row, key),
            )
        )
    return sales


def _tx(row: dict, key: str, common: dict, kind: FinancialTransactionType, amount: Decimal, suffix: str, raw: str, **extra_fields) -> FinancialTransaction:
    return FinancialTransaction(
        transaction_id=f"{key}:{suffix}",
        transaction_type=kind,
        raw_transaction_type=raw,
        debit=abs(amount) if amount < 0 else Decimal("0"),
        credit=amount if amount > 0 else Decimal("0"),
        net_amount=amount,
        provider_meta=_meta(row, f"{key}:{suffix}"),
        **{**common, **extra_fields, "extra": {**common["extra"], **extra_fields.get("extra", {})}},
    )


def transactions_from_detailed(payload: dict, day: date) -> list[FinancialTransaction]:
    apps = _names(payload, "app_info", "appid", "app_name")
    period = f"{day:%Y-%m}"
    result: list[FinancialTransaction] = []
    for row in payload.get("results", []) or []:
        if not _has_activity(row):
            continue
        key = _row_key(row, day)
        title = apps.get(_app_id(row), "")
        common = {
            "transaction_date": _at(day),
            "description": title,
            "currency": CURRENCY,
            "payout_id": f"{period}:{CURRENCY}",
            "extra": {"country": row.get("country_code", ""), "app_id": _app_id(row), "sku": str(row.get("packageid", "")), "units": _int(row, "net_units_sold"), "package_sale_type": row.get("package_sale_type", "")},
        }

        gross = _money(row.get("gross_sales_usd") or 0)
        returns = _money(row.get("gross_returns_usd", 0))
        tax = _money(row.get("net_tax_usd", 0))
        net_sales = _money(row.get("net_sales_usd", 0))
        tier = BONUS_TIERS.get(_int(row, "additional_revenue_share_tier"), Decimal("0"))
        commission = (net_sales * (REVENUE_SHARE - tier)).quantize(CENT, rounding=ROUND_HALF_UP)
        if gross:
            result.append(_tx(row, key, common, FinancialTransactionType.SALE, gross, "sale", "gross_sales_usd"))
        if returns:
            # Steam trimite gross_returns_usd deja negativ pe randurile de retur
            result.append(_tx(row, key, common, FinancialTransactionType.RETURN, returns, "return", "gross_returns_usd"))
        if tax:
            result.append(_tx(row, key, common, FinancialTransactionType.DEDUCTION, -tax, "tax", "net_tax_usd"))
        if net_sales:
            result.append(
                _tx(
                    row,
                    key,
                    common,
                    FinancialTransactionType.COMMISSION,
                    -commission,
                    "commission",
                    "revenue_share",
                    commission_rate=(REVENUE_SHARE - tier) * 100,
                    commission_amount=commission,
                    extra={"estimated": True},
                )
            )
    return result


def refunds_from_detailed(payload: dict, day: date) -> list[AppStoreRefund]:
    refunds = []
    for row in payload.get("results", []) or []:
        returned = abs(_int(row, "gross_units_returned"))  # vine negativ la Steam
        if not returned:
            continue
        key = _row_key(row, day)
        refunds.append(
            AppStoreRefund(
                refund_id=f"{key}:return",
                app_id=_app_id(row),
                sku=str(row.get("packageid", "")),
                amount=abs(_money(row.get("gross_returns_usd", 0))),
                currency=CURRENCY,
                refunded_at=_at(day),
                extra={"units": returned, "country": row.get("country_code", "")},
                provider_meta=_meta(row, f"{key}:return"),
            )
        )
    return refunds


def app_from_details(app_id: str, details: dict | None) -> AppStoreApp:
    data = ((details or {}).get(str(app_id)) or {}).get("data") or {}
    return AppStoreApp(app_id=str(app_id), platform=AppStorePlatform.STEAM, name=data.get("name", "") or str(app_id), bundle_id=str(app_id), extra={"type": data.get("type", "")})


def review_from_steam(data: dict, app_id: str) -> AppStoreReview:
    author = data.get("author") or {}
    created = datetime.fromtimestamp(int(data.get("timestamp_created", 0) or 0), tz=UTC) if data.get("timestamp_created") else None
    updated = datetime.fromtimestamp(int(data.get("timestamp_updated", 0) or 0), tz=UTC) if data.get("timestamp_updated") else created
    return AppStoreReview(
        review_id=str(data.get("recommendationid", "")),
        app_id=str(app_id),
        recommended=bool(data.get("voted_up")),
        body=data.get("review", "") or "",
        author=str(author.get("steamid", "")),
        language=data.get("language", ""),
        created_at=created,
        updated_at=updated,
        extra={"votes_up": data.get("votes_up"), "playtime_minutes": author.get("playtime_forever"), "steam_purchase": data.get("steam_purchase")},
        provider_meta=_meta(data, str(data.get("recommendationid", ""))),
    )
