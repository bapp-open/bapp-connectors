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

#: line_item_type (Steamworks): 1 = vanzare pachet, 2 = DLC, 3 = microtranzactie/item, altele = OTHER
LINE_ITEM_TYPES = {1: AppStoreProductType.APP, 2: AppStoreProductType.DLC, 3: AppStoreProductType.IAP}


def _meta(raw: dict, raw_id: str = "") -> ProviderMeta:
    return ProviderMeta(provider=PROVIDER, raw_id=raw_id, raw_payload=raw, fetched_at=datetime.now(UTC))


def _names(payload: dict, key: str, id_key: str) -> dict[str, str]:
    return {str(item.get(id_key)): item.get("name", "") for item in payload.get(key, []) or []}


def _money(value) -> Decimal:
    return to_decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _row_key(row: dict, day: date) -> str:
    return stable_key(PROVIDER, day, *(row.get(k) for k in ("line_item_type", "packageid", "bundleid", "appid", "game_item_id", "package_sale_type", "key_request_id", "platform", "country_code", "base_price", "sale_price")))


def _at(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def sales_from_detailed(payload: dict, day: date) -> list[AppStoreSale]:
    apps = _names(payload, "app_info", "appid")
    packages = _names(payload, "package_info", "packageid")
    sales = []
    for row in payload.get("results", []) or []:
        key = _row_key(row, day)
        product_type = LINE_ITEM_TYPES.get(int(row.get("line_item_type", 0)), AppStoreProductType.OTHER)
        if int(row.get("bundleid", 0) or 0):
            product_type = AppStoreProductType.APP
        net_units = Decimal(str(row.get("net_units_sold", 0)))
        sales.append(
            AppStoreSale(
                external_key=key,
                period_start=day,
                period_end=day,
                app_id=str(row.get("appid", "")),
                sku=str(row.get("packageid") or row.get("bundleid") or row.get("game_item_id") or ""),
                product_name=packages.get(str(row.get("packageid")), "") or apps.get(str(row.get("appid")), ""),
                product_type=product_type,
                units=net_units,
                country=row.get("country_code", ""),
                customer_currency=CURRENCY,
                customer_price=_money(row.get("avg_sale_price_usd", 0)),
                proceeds_currency=CURRENCY,
                proceeds_unit=(_money(row.get("net_sales_usd", 0)) / net_units).quantize(CENT) if net_units else Decimal("0"),
                proceeds_total=_money(row.get("net_sales_usd", 0)),
                is_refund=False,
                extra={
                    "gross_units_sold": int(row.get("gross_units_sold", 0) or 0),
                    "gross_units_returned": int(row.get("gross_units_returned", 0) or 0),
                    "gross_sales_usd": str(_money(row.get("gross_sales_usd", 0))),
                    "gross_returns_usd": str(_money(row.get("gross_returns_usd", 0))),
                    "net_tax_usd": str(_money(row.get("net_tax_usd", 0))),
                    "platform": row.get("platform", ""),
                    "app_name": apps.get(str(row.get("appid")), ""),
                    "revenue_share_tier": int(row.get("additional_revenue_share_tier", 0) or 0),
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
    apps = _names(payload, "app_info", "appid")
    period = f"{day:%Y-%m}"
    result: list[FinancialTransaction] = []
    for row in payload.get("results", []) or []:
        key = _row_key(row, day)
        title = apps.get(str(row.get("appid")), "")
        common = {
            "transaction_date": _at(day),
            "description": title,
            "currency": CURRENCY,
            "payout_id": f"{period}:{CURRENCY}",
            "extra": {"country": row.get("country_code", ""), "app_id": str(row.get("appid", "")), "sku": str(row.get("packageid", "")), "units": int(row.get("net_units_sold", 0) or 0)},
        }

        gross = _money(row.get("gross_sales_usd", 0))
        returns = _money(row.get("gross_returns_usd", 0))
        tax = _money(row.get("net_tax_usd", 0))
        net_sales = _money(row.get("net_sales_usd", 0))
        tier = BONUS_TIERS.get(int(row.get("additional_revenue_share_tier", 0) or 0), Decimal("0"))
        commission = (net_sales * (REVENUE_SHARE - tier)).quantize(CENT, rounding=ROUND_HALF_UP)
        if gross:
            result.append(_tx(row, key, common, FinancialTransactionType.SALE, gross, "sale", "gross_sales_usd"))
        if returns:
            result.append(_tx(row, key, common, FinancialTransactionType.RETURN, -returns, "return", "gross_returns_usd"))
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
        returned = int(row.get("gross_units_returned", 0) or 0)
        if not returned:
            continue
        key = _row_key(row, day)
        refunds.append(
            AppStoreRefund(
                refund_id=f"{key}:return",
                app_id=str(row.get("appid", "")),
                sku=str(row.get("packageid", "")),
                amount=_money(row.get("gross_returns_usd", 0)),
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
