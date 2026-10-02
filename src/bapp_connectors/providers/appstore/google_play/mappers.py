"""Conversii Google Play (CSV din bucket, Android Publisher JSON, RTDN) <-> DTO-uri."""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlparse

from bapp_connectors.core.dto import (
    AppStoreApp,
    AppStorePlatform,
    AppStoreProductType,
    AppStoreRefund,
    AppStoreReview,
    AppStoreSale,
    AppStoreStat,
    AppStoreStatMetric,
    FinancialTransaction,
    FinancialTransactionType,
    ProviderMeta,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
    WebhookEventType,
)
from bapp_connectors.core.reports import stable_key, to_decimal
from bapp_connectors.providers.appstore.google_play.errors import GooglePlayWebhookError

PROVIDER = "google_play"

PRODUCT_TYPE_MAP = {
    "paidapp": AppStoreProductType.APP,
    "paid app": AppStoreProductType.APP,
    "inapp": AppStoreProductType.IAP,
    "in-app": AppStoreProductType.IAP,
    "subscription": AppStoreProductType.SUBSCRIPTION,
}

EARNINGS_TYPE_MAP: dict[str, FinancialTransactionType] = {
    "charge": FinancialTransactionType.SALE,
    "charge rebill": FinancialTransactionType.SALE,
    "google fee": FinancialTransactionType.COMMISSION,
    "google fee rebill": FinancialTransactionType.COMMISSION,
    "tax": FinancialTransactionType.DEDUCTION,
    "tax rebill": FinancialTransactionType.DEDUCTION,
    "charge refund": FinancialTransactionType.RETURN,
    "google fee refund": FinancialTransactionType.OTHER,
    "tax refund": FinancialTransactionType.OTHER,
    "adjustment": FinancialTransactionType.OTHER,
}

VOIDED_REASONS = {0: "other", 1: "remorse", 2: "not_received", 3: "defective", 4: "accidental_purchase", 5: "fraud", 6: "friendly_fraud", 7: "chargeback", 8: "unacknowledged_purchase"}


def _col(row: dict, *names: str, default: str = "") -> str:
    """Prima coloana prezenta (non-None) dintre `names`: exact, apoi fara diferente de majuscule."""
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return default


def _meta(raw: dict, raw_id: str = "") -> ProviderMeta:
    return ProviderMeta(provider=PROVIDER, raw_id=raw_id, raw_payload=raw, fetched_at=datetime.now(UTC))


def parse_earnings_date(text: str) -> date | None:
    """`Sep 3, 2026` (earnings) sau `2026-09-03` (sales)."""
    text = text.strip()
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _from_millis(value) -> datetime | None:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms else None


def _from_seconds_field(value) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("seconds")
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return None


def app_from_package(package_name: str, title: str = "") -> AppStoreApp:
    return AppStoreApp(app_id=package_name, platform=AppStorePlatform.GOOGLE_PLAY, name=title or package_name, bundle_id=package_name)


def sale_from_sales_row(row: dict, year: int, month: int) -> AppStoreSale:
    status = row.get("Financial Status", "").strip().lower()
    is_refund = bool(status) and status != "charged"
    charged = parse_earnings_date(row.get("Order Charged Date", "")) or date(year, month, 1)
    sku = _col(row, "SKU ID", "Sku Id")
    key = stable_key(PROVIDER, row.get("Order Number"), sku, status, row.get("Charged Amount"))
    units = Decimal("-1") if is_refund else Decimal("1")
    return AppStoreSale(
        external_key=key,
        period_start=charged,
        period_end=charged,
        app_id=_col(row, "Product ID", "Product id", "Package ID"),
        sku=sku,
        product_name=row.get("Product Title", ""),
        product_type=PRODUCT_TYPE_MAP.get(row.get("Product Type", "").strip().lower(), AppStoreProductType.OTHER),
        units=units,
        country=row.get("Country of Buyer", ""),
        customer_currency=row.get("Currency of Sale", ""),
        customer_price=to_decimal(row.get("Item Price")),
        proceeds_currency=row.get("Currency of Sale", ""),
        proceeds_unit=Decimal("0"),  # cota dezvoltatorului vine din earnings, nu din sales
        proceeds_total=Decimal("0"),
        is_refund=is_refund,
        extra={
            "order_number": row.get("Order Number", ""),
            "financial_status": row.get("Financial Status", ""),
            "taxes_collected": str(to_decimal(row.get("Taxes Collected"))),
            "charged_amount": str(to_decimal(row.get("Charged Amount"))),
            "base_plan": _col(row, "Base Plan ID", "Base Plan or Purchase Option ID"),
            "offer_id": row.get("Offer ID", ""),
            "postal_code": _col(row, "Postal Code of Buyer", "Postcode of Buyer"),
            "featured_product_id": _col(row, "Featured Product ID", "Featured Products ID"),
            "device": row.get("Device Model", ""),
        },
        provider_meta=_meta(row, key),
    )


def transactions_from_earnings_rows(rows: list[dict], year: int, month: int) -> list[FinancialTransaction]:
    period = f"{year:04d}{month:02d}"
    seen: dict[str, int] = {}
    result: list[FinancialTransaction] = []
    for row in rows:
        raw_type = row.get("Transaction Type", "").strip()
        tx_type = EARNINGS_TYPE_MAP.get(raw_type.lower(), FinancialTransactionType.OTHER)
        amount = to_decimal(row.get("Amount (Merchant Currency)"))
        currency = row.get("Merchant Currency", "")
        base_key = stable_key(PROVIDER, period, *(row.get(col, "") for col in sorted(row)))
        count = seen.get(base_key, 0) + 1
        seen[base_key] = count
        tx_id = base_key if count == 1 else f"{base_key}:{count}"
        tx_day = parse_earnings_date(row.get("Transaction Date", ""))
        result.append(
            FinancialTransaction(
                transaction_id=tx_id,
                transaction_type=tx_type,
                raw_transaction_type=raw_type,
                transaction_date=datetime.combine(tx_day, datetime.min.time(), tzinfo=UTC) if tx_day else None,
                description=row.get("Product Title", ""),
                currency=currency,
                debit=abs(amount) if amount < 0 else Decimal("0"),
                credit=amount if amount > 0 else Decimal("0"),
                net_amount=amount,
                commission_amount=abs(amount) if tx_type == FinancialTransactionType.COMMISSION else None,
                commission_rate=to_decimal(row.get("Service Fee %")) if row.get("Service Fee %") else None,
                order_id=row.get("Description", ""),
                payout_id=f"{period}:{currency}",
                extra={
                    "package_id": _col(row, "Product id", "Product ID", "Package ID"),
                    "sku": _col(row, "Sku Id", "SKU ID", "Sku ID"),
                    "product_type": row.get("Product Type", ""),
                    "country": row.get("Buyer Country", ""),
                    "buyer_currency": row.get("Buyer Currency", ""),
                    "buyer_amount": str(to_decimal(row.get("Amount (Buyer Currency)"))),
                    "conversion_rate": row.get("Currency Conversion Rate", ""),
                    "refund_type": row.get("Refund Type", ""),
                    "tax_type": row.get("Tax Type", ""),
                    "base_plan": _col(row, "Base Plan ID", "Base Plan or Purchase Option ID"),
                    "postal_code": _col(row, "Buyer Postal Code", "Buyer Postcode"),
                },
                provider_meta=_meta(row, tx_id),
            )
        )
    return result


def _review_id_from_link(link: str) -> str:
    query = parse_qs(urlparse(link).query)
    values = query.get("reviewId") or []
    return unquote(values[0]) if values else ""


def review_from_csv_row(row: dict, package_name: str) -> AppStoreReview:
    review_id = _review_id_from_link(row.get("Review Link", "")) or stable_key(PROVIDER, package_name, row.get("Review Submit Millis Since Epoch"), row.get("Review Text"))
    rating = to_decimal(row.get("Star Rating"))
    reply_at = _from_millis(row.get("Developer Reply Millis Since Epoch"))
    return AppStoreReview(
        review_id=review_id,
        app_id=package_name,
        rating=int(rating) if rating else None,
        title=row.get("Review Title", ""),
        body=row.get("Review Text", ""),
        language=row.get("Reviewer Language", ""),
        app_version=row.get("App Version Name", ""),
        created_at=_from_millis(row.get("Review Submit Millis Since Epoch")),
        updated_at=_from_millis(row.get("Review Last Update Millis Since Epoch")),
        developer_response=row.get("Developer Reply Text", ""),
        developer_response_at=reply_at,
        extra={"device": row.get("Device", ""), "app_version_code": row.get("App Version Code", "")},
        provider_meta=_meta(row, review_id),
    )


def review_from_api(data: dict, package_name: str) -> AppStoreReview:
    user: dict = {}
    developer: dict = {}
    for comment in data.get("comments", []):
        if "userComment" in comment:
            user = comment["userComment"]
        if "developerComment" in comment:
            developer = comment["developerComment"]
    text = (user.get("text") or "").strip()
    title, _, body = text.partition("\t") if "\t" in text else ("", "", text)
    modified = _from_seconds_field(user.get("lastModified"))
    return AppStoreReview(
        review_id=data.get("reviewId", ""),
        app_id=package_name,
        rating=user.get("starRating"),
        title=title.strip(),
        body=body.strip(),
        author=data.get("authorName", ""),
        language=user.get("reviewerLanguage", ""),
        app_version=user.get("appVersionName", "") or "",
        created_at=modified,
        updated_at=modified,
        developer_response=(developer.get("text") or "").strip(),
        developer_response_at=_from_seconds_field(developer.get("lastModified")),
        extra={"device": user.get("device", ""), "android_os_version": user.get("androidOsVersion")},
        provider_meta=_meta(data, data.get("reviewId", "")),
    )


def refund_from_voided(data: dict, package_name: str) -> AppStoreRefund:
    return AppStoreRefund(
        refund_id=data.get("orderId") or data.get("purchaseToken", ""),
        app_id=package_name,
        transaction_ref=data.get("purchaseToken", ""),
        reason=VOIDED_REASONS.get(data.get("voidedReason"), "unknown") if data.get("voidedReason") is not None else "",
        refunded_at=_from_millis(data.get("voidedTimeMillis")),
        extra={"voided_source": data.get("voidedSource"), "purchased_at": (_from_millis(data.get("purchaseTimeMillis")) or datetime.min).isoformat()},
        provider_meta=_meta(data, data.get("orderId", "")),
    )


V2_STATE_MAP = {
    "SUBSCRIPTION_STATE_ACTIVE": SubscriptionStatus.ACTIVE,
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": SubscriptionStatus.PAST_DUE,
    "SUBSCRIPTION_STATE_ON_HOLD": SubscriptionStatus.UNPAID,
    "SUBSCRIPTION_STATE_PAUSED": SubscriptionStatus.PAUSED,
    "SUBSCRIPTION_STATE_CANCELED": SubscriptionStatus.CANCELLED,
    "SUBSCRIPTION_STATE_EXPIRED": SubscriptionStatus.CANCELLED,
    "SUBSCRIPTION_STATE_PENDING": SubscriptionStatus.PENDING,
}


def _parse_rfc3339(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def subscription_from_v2(payload: dict, purchase_token: str) -> Subscription:
    line = (payload.get("lineItems") or [{}])[0]
    auto_renew = (line.get("autoRenewingPlan") or {}).get("autoRenewEnabled")
    return Subscription(
        subscription_id=purchase_token,
        status=V2_STATE_MAP.get(payload.get("subscriptionState", ""), SubscriptionStatus.PENDING),
        price_id=line.get("productId", ""),
        current_period_end=_parse_rfc3339(line.get("expiryTime")),
        cancel_at_period_end=auto_renew is False,
        created_at=_parse_rfc3339(payload.get("startTime")),
        extra={
            "purchase_token": purchase_token,
            "product_id": line.get("productId", ""),
            "latest_order_id": payload.get("latestOrderId", ""),
            "state": payload.get("subscriptionState", ""),
            "region_code": payload.get("regionCode", ""),
        },
        provider_meta=_meta(payload, purchase_token),
    )


#: RTDN: subscriptionNotification.notificationType -> tip normalizat
RTDN_SUBSCRIPTION_MAP = {
    1: WebhookEventType.SUBSCRIPTION_PAYMENT_SUCCEEDED,  # RECOVERED
    2: WebhookEventType.SUBSCRIPTION_RENEWED,
    3: WebhookEventType.SUBSCRIPTION_CANCELLED,
    4: WebhookEventType.SUBSCRIPTION_CREATED,  # PURCHASED
    5: WebhookEventType.SUBSCRIPTION_PAYMENT_FAILED,  # ON_HOLD
    6: WebhookEventType.SUBSCRIPTION_PAYMENT_FAILED,  # IN_GRACE_PERIOD
    7: WebhookEventType.SUBSCRIPTION_UPDATED,  # RESTARTED
    8: WebhookEventType.SUBSCRIPTION_UPDATED,  # PRICE_CHANGE_CONFIRMED
    9: WebhookEventType.SUBSCRIPTION_UPDATED,  # DEFERRED
    10: WebhookEventType.SUBSCRIPTION_UPDATED,  # PAUSED
    11: WebhookEventType.SUBSCRIPTION_UPDATED,  # PAUSE_SCHEDULE_CHANGED
    12: WebhookEventType.SUBSCRIPTION_CANCELLED,  # REVOKED
    13: WebhookEventType.SUBSCRIPTION_EXPIRED,
    20: WebhookEventType.SUBSCRIPTION_UPDATED,  # PENDING_PURCHASE_CANCELED
}


def _notification_type(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def webhook_event_from_pubsub(message: dict) -> WebhookEvent:
    """`message` = corpul `message` din push-ul Pub/Sub; `data` e base64 cu JSON-ul RTDN."""
    if not message.get("messageId"):
        raise GooglePlayWebhookError("Mesaj Pub/Sub fara messageId")
    try:
        raw = base64.b64decode(message.get("data") or "").decode("utf-8") if message.get("data") else "{}"
        rtdn = json.loads(raw) if raw else {}
    except (ValueError, TypeError) as exc:
        raise GooglePlayWebhookError(f"RTDN invalid: {exc}") from exc
    if not isinstance(rtdn, dict):
        raise GooglePlayWebhookError("RTDN invalid: corpul nu este un obiect JSON")
    package_name = rtdn.get("packageName", "")
    if "subscriptionNotification" in rtdn:
        sub = rtdn["subscriptionNotification"]
        kind = _notification_type(sub.get("notificationType"))
        event_type = RTDN_SUBSCRIPTION_MAP.get(kind, WebhookEventType.UNKNOWN)
        provider_type = f"subscriptionNotification/{kind}"
        payload = {"purchase_token": sub.get("purchaseToken", ""), "product_id": sub.get("subscriptionId", ""), "package_name": package_name}
    elif "voidedPurchaseNotification" in rtdn:
        voided = rtdn["voidedPurchaseNotification"]
        event_type = WebhookEventType.PURCHASE_REFUNDED
        provider_type = "voidedPurchaseNotification"
        payload = {"purchase_token": voided.get("purchaseToken", ""), "order_id": voided.get("orderId", ""), "product_type": voided.get("productType"), "refund_type": voided.get("refundType"), "package_name": package_name}
    elif "oneTimeProductNotification" in rtdn:
        one = rtdn["oneTimeProductNotification"]
        event_type = WebhookEventType.PAYMENT_COMPLETED if _notification_type(one.get("notificationType")) == 1 else WebhookEventType.UNKNOWN
        provider_type = f"oneTimeProductNotification/{one.get('notificationType')}"
        payload = {"purchase_token": one.get("purchaseToken", ""), "product_id": one.get("sku", ""), "package_name": package_name}
    else:
        event_type = WebhookEventType.UNKNOWN
        provider_type = "testNotification" if "testNotification" in rtdn else "unknown"
        payload = {"package_name": package_name}
    event_time = _from_millis(rtdn.get("eventTimeMillis"))
    return WebhookEvent(
        event_id=message.get("messageId", ""),
        event_type=event_type,
        provider=PROVIDER,
        provider_event_type=provider_type,
        payload=payload,
        idempotency_key=message.get("messageId", ""),
        received_at=event_time or datetime.now(UTC),
        extra={"version": rtdn.get("version", ""), "publish_time": message.get("publishTime", "")},
        provider_meta=_meta({"message": message, "rtdn": rtdn}, message.get("messageId", "")),
    )


# ── statistici (stats/ din bucket) ──

_INSTALL_METRICS = (
    (AppStoreStatMetric.INSTALLS, "Daily Device Installs"),
    (AppStoreStatMetric.UNINSTALLS, "Daily Device Uninstalls"),
    (AppStoreStatMetric.ACTIVE_DEVICES, "Active Device Installs"),
    (AppStoreStatMetric.USER_INSTALLS, "Daily User Installs"),
)
_INSTALL_EXTRA = (
    ("daily_device_upgrades", "Daily Device Upgrades"),
    ("total_user_installs", "Total User Installs"),
    ("daily_user_uninstalls", "Daily User Uninstalls"),
    ("install_events", "Install events"),
    ("update_events", "Update events"),
    ("uninstall_events", "Uninstall events"),
)


def _stat(day: date, app_id: str, metric: AppStoreStatMetric, raw: str, country: str = "", extra: dict | None = None) -> AppStoreStat:
    extra = extra or {}
    return AppStoreStat(
        external_key=stable_key(PROVIDER, day, app_id, metric, country, extra.get("traffic_source", "")),
        date=day,
        metric=metric,
        value=to_decimal(raw),
        app_id=app_id,
        country=country,
        extra=extra,
    )


def stats_from_installs_rows(rows: list[dict], app_id: str, country_column: str | None = None) -> list[AppStoreStat]:
    """`installs_*_overview.csv` (country_column=None) sau `installs_*_country.csv` (country_column="Country")."""
    stats: list[AppStoreStat] = []
    for row in rows:
        day = parse_earnings_date(_col(row, "Date"))
        if day is None:
            continue
        country = _col(row, country_column).strip() if country_column else ""
        extra = {key: _col(row, column).strip() for key, column in _INSTALL_EXTRA}
        for metric, column in _INSTALL_METRICS:
            stats.append(_stat(day, app_id, metric, _col(row, column), country, dict(extra)))
    return stats


def stats_from_ratings_rows(rows: list[dict], app_id: str) -> list[AppStoreStat]:
    stats: list[AppStoreStat] = []
    for row in rows:
        day = parse_earnings_date(_col(row, "Date"))
        if day is None:
            continue
        for metric, column in ((AppStoreStatMetric.RATING_DAILY, "Daily Average Rating"), (AppStoreStatMetric.RATING_TOTAL, "Total Average Rating")):
            raw = _col(row, column).strip()
            if raw:  # ziua fara evaluari are celula goala, nu 0
                stats.append(_stat(day, app_id, metric, raw))
    return stats


def stats_from_crashes_rows(rows: list[dict], app_id: str) -> list[AppStoreStat]:
    stats: list[AppStoreStat] = []
    for row in rows:
        day = parse_earnings_date(_col(row, "Date"))
        if day is None:
            continue
        stats.append(_stat(day, app_id, AppStoreStatMetric.CRASHES, _col(row, "Daily Crashes")))
        stats.append(_stat(day, app_id, AppStoreStatMetric.ANRS, _col(row, "Daily ANRs")))
    return stats


def stats_from_store_rows(rows: list[dict], app_id: str, by: str = "traffic_source") -> list[AppStoreStat]:
    """`total_store_performance_*_traffic_source.csv` (by="traffic_source") sau `..._country.csv` (by="country")."""
    stats: list[AppStoreStat] = []
    for row in rows:
        day = parse_earnings_date(_col(row, "Date"))
        if day is None:
            continue
        country = _col(row, "Country").strip() if by == "country" else ""
        extra = {"traffic_source": _col(row, "Traffic source").strip()} if by == "traffic_source" else {}
        stats.append(_stat(day, app_id, AppStoreStatMetric.STORE_ACQUISITIONS, _col(row, "Total store acquisitions"), country, extra))
    return stats
