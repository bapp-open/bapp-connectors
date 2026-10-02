"""Conversii Apple API / rapoarte TSV <-> DTO-uri."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

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
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
    WebhookEventType,
)
from bapp_connectors.core.reports import stable_key, to_decimal
from bapp_connectors.providers.appstore.apple.fiscal_calendar import payment_date

PROVIDER = "apple"

#: Product Type Identifier -> tip normalizat (sursa: App Store Connect Help, „Product type identifiers").
PRODUCT_TYPE_MAP: dict[str, AppStoreProductType] = {
    **dict.fromkeys(["1", "1F", "1T", "1E", "1EP", "1EU", "F1", "1-B", "F1-B"], AppStoreProductType.APP),
    **dict.fromkeys(["IA1", "IA1-M", "IA3", "IA9", "IA9-M", "FI1"], AppStoreProductType.IAP),
    **dict.fromkeys(["IAY", "IAY-M"], AppStoreProductType.SUBSCRIPTION_NEW),  # rafinat dupa coloana Subscription
}
#: Re-descarcari si update-uri: unitati fara bani, nu sunt vanzari.
SKIP_PRODUCT_TYPES = frozenset({"3", "3F", "7", "7F", "7T", "F7"})
SUBSCRIPTION_TYPES = frozenset({"IAY", "IAY-M"})


def parse_apple_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%m/%d/%Y").date()


def _iso_date(text: str | None) -> str:
    return parse_apple_date(text).isoformat() if text else ""


def parse_iso_datetime(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _meta(raw: dict, raw_id: str = "") -> ProviderMeta:
    return ProviderMeta(provider=PROVIDER, raw_id=raw_id, raw_payload=raw, fetched_at=datetime.now(UTC))


def _product_type(row: dict) -> AppStoreProductType:
    identifier = row.get("Product Type Identifier", "")
    kind = PRODUCT_TYPE_MAP.get(identifier, AppStoreProductType.OTHER)
    if identifier in SUBSCRIPTION_TYPES:
        return AppStoreProductType.SUBSCRIPTION_RENEWAL if row.get("Subscription", "").lower() == "renewal" else AppStoreProductType.SUBSCRIPTION_NEW
    return kind


def sale_from_sales_row(row: dict, report_date: date) -> AppStoreSale | None:
    identifier = row.get("Product Type Identifier", "")
    if identifier in SKIP_PRODUCT_TYPES:
        return None
    units = to_decimal(row.get("Units"))
    proceeds_unit = to_decimal(row.get("Developer Proceeds"))
    begin = parse_apple_date(row["Begin Date"]) if row.get("Begin Date") else report_date
    end = parse_apple_date(row["End Date"]) if row.get("End Date") else report_date
    key = stable_key(
        PROVIDER, begin, end, row.get("SKU"), row.get("Country Code"), identifier, row.get("Subscription"),
        row.get("Customer Currency"), row.get("Customer Price"), row.get("Currency of Proceeds"),
        row.get("Developer Proceeds"), row.get("Promo Code"), row.get("Order Type"), row.get("Device"),
        row.get("Proceeds Reason"), row.get("Version"), row.get("Client"), row.get("Preserved Pricing"),
        row.get("Period"), row.get("Supported Platforms"), row.get("Apple Identifier"),
        row.get("Parent Identifier"), "refund" if units < 0 else "sale",
    )
    return AppStoreSale(
        external_key=key,
        period_start=begin,
        period_end=end,
        app_id=row.get("Apple Identifier", ""),
        sku=row.get("SKU", ""),
        product_name=row.get("Title", ""),
        product_type=_product_type(row),
        units=units,
        country=row.get("Country Code", ""),
        customer_currency=row.get("Customer Currency", ""),
        customer_price=to_decimal(row.get("Customer Price")),
        proceeds_currency=row.get("Currency of Proceeds", ""),
        proceeds_unit=proceeds_unit,
        proceeds_total=(units * proceeds_unit).quantize(Decimal("0.01")),
        is_refund=units < 0,
        extra={
            "product_type_identifier": identifier,
            "parent_identifier": row.get("Parent Identifier", ""),
            "subscription": row.get("Subscription", ""),
            "period": row.get("Period", ""),
            "device": row.get("Device", ""),
            "promo_code": row.get("Promo Code", ""),
            "order_type": row.get("Order Type", ""),
            "proceeds_reason": row.get("Proceeds Reason", ""),
            "version": row.get("Version", ""),
        },
        provider_meta=_meta(row, key),
    )


def refund_from_sale(sale: AppStoreSale) -> AppStoreRefund:
    return AppStoreRefund(
        refund_id=sale.external_key,
        app_id=sale.app_id,
        sku=sale.sku,
        amount=abs(sale.customer_price * sale.units).quantize(Decimal("0.01")),
        currency=sale.customer_currency,
        reason=sale.extra.get("proceeds_reason", ""),
        refunded_at=datetime.combine(sale.period_start, time.min, tzinfo=UTC),
        extra={"units": str(sale.units), "country": sale.country},
        provider_meta=sale.provider_meta,
    )


def transaction_from_finance_row(row: dict, fiscal_period: str, preamble: dict | None = None) -> FinancialTransaction:
    preamble = preamble or {}
    amount = to_decimal(row.get("Extended Partner Share"))
    is_return = row.get("Sale or Return", "S").upper() == "R" or amount < 0
    currency = row.get("Partner Share Currency", "")
    tx_date = row.get("Transaction Date") or preamble.get("Start Date") or row.get("Start Date") or ""
    settlement = row.get("Settlement Date") or ""
    key = stable_key(
        PROVIDER, fiscal_period, row.get("SKU"), row.get("Country of Sale"), row.get("Product Type Identifier"),
        tx_date, settlement, row.get("Sale or Return"), row.get("Quantity"), row.get("Partner Share"),
        currency, row.get("Customer Price"), row.get("Customer Currency"), row.get("Promo Code"), row.get("Order Type"),
    )
    pay_date = payment_date(fiscal_period)
    return FinancialTransaction(
        transaction_id=key,
        transaction_type=FinancialTransactionType.RETURN if is_return else FinancialTransactionType.SALE,
        raw_transaction_type=row.get("Sale or Return", ""),
        transaction_date=datetime.combine(parse_apple_date(tx_date), time.min, tzinfo=UTC) if tx_date else None,
        description=row.get("Title", ""),
        currency=currency,
        debit=abs(amount) if amount < 0 else Decimal("0"),
        credit=amount if amount > 0 else Decimal("0"),
        net_amount=amount,
        payment_date=datetime.combine(pay_date, time.min, tzinfo=UTC) if pay_date else None,
        payout_id=f"{fiscal_period}:{currency}",
        extra={
            "fiscal_period": fiscal_period,
            "settlement_date": settlement,
            "units": int(to_decimal(row.get("Quantity"))),
            "country": row.get("Country of Sale", ""),
            "sku": row.get("SKU", ""),
            "app_id": row.get("Apple Identifier", ""),
            "product_type_identifier": row.get("Product Type Identifier", ""),
            "partner_share": str(to_decimal(row.get("Partner Share"))),
            "customer_price": str(to_decimal(row.get("Customer Price"))),
            "customer_currency": row.get("Customer Currency", ""),
            "order_type": row.get("Order Type", ""),
            "period_start": _iso_date(preamble.get("Start Date")),
            "period_end": _iso_date(preamble.get("End Date")),
        },
        provider_meta=_meta(row, key),
    )


def app_from_apple(data: dict) -> AppStoreApp:
    attrs = data.get("attributes") or {}
    return AppStoreApp(
        app_id=str(data.get("id", "")),
        platform=AppStorePlatform.APPLE,
        name=attrs.get("name", ""),
        bundle_id=attrs.get("bundleId", ""),
        extra={"sku": attrs.get("sku", "")},
        provider_meta=_meta(data, str(data.get("id", ""))),
    )


def review_from_apple(data: dict, responses_by_id: dict[str, dict], app_id: str) -> AppStoreReview:
    attrs = data.get("attributes") or {}
    response_ref = ((data.get("relationships") or {}).get("response") or {}).get("data") or {}
    response = responses_by_id.get(response_ref.get("id", ""), {}) if response_ref else {}
    response_attrs = response.get("attributes") or {}
    created = parse_iso_datetime(attrs.get("createdDate"))
    return AppStoreReview(
        review_id=str(data.get("id", "")),
        app_id=app_id,
        rating=attrs.get("rating"),
        title=attrs.get("title", "") or "",
        body=attrs.get("body", "") or "",
        author=attrs.get("reviewerNickname", "") or "",
        country=attrs.get("territory", "") or "",
        created_at=created,
        updated_at=created,
        developer_response=response_attrs.get("responseBody", "") or "",
        developer_response_at=parse_iso_datetime(response_attrs.get("lastModifiedDate")),
        extra={"response_state": response_attrs.get("state", "")},
        provider_meta=_meta(data, str(data.get("id", ""))),
    )


#: status din App Store Server API (`data[].lastTransactions[].status`)
SERVER_STATUS_MAP: dict[int, SubscriptionStatus] = {
    1: SubscriptionStatus.ACTIVE,
    2: SubscriptionStatus.CANCELLED,  # expired
    3: SubscriptionStatus.PAST_DUE,  # billing retry
    4: SubscriptionStatus.PAST_DUE,  # grace period
    5: SubscriptionStatus.CANCELLED,  # revoked
}


def subscription_from_server_status(status: int, transaction: dict, renewal: dict) -> Subscription:
    expires_ms = transaction.get("expiresDate")
    purchase_ms = transaction.get("originalPurchaseDate") or transaction.get("purchaseDate")
    return Subscription(
        subscription_id=str(transaction.get("originalTransactionId", "")),
        status=SERVER_STATUS_MAP.get(status, SubscriptionStatus.PENDING),
        price_id=transaction.get("productId", ""),
        amount=Decimal(str(transaction.get("price", 0))) / 1000 if transaction.get("price") is not None else Decimal("0"),
        currency=transaction.get("currency", ""),
        current_period_end=datetime.fromtimestamp(expires_ms / 1000, tz=UTC) if expires_ms else None,
        cancel_at_period_end=renewal.get("autoRenewStatus") == 0,
        created_at=datetime.fromtimestamp(purchase_ms / 1000, tz=UTC) if purchase_ms else None,
        extra={
            "product_id": transaction.get("productId", ""),
            "original_transaction_id": transaction.get("originalTransactionId", ""),
            "environment": transaction.get("environment", ""),
            "bundle_id": transaction.get("bundleId", ""),
            "auto_renew_product_id": renewal.get("autoRenewProductId", ""),
        },
        provider_meta=_meta({"transaction": transaction, "renewal": renewal, "status": status}, str(transaction.get("originalTransactionId", ""))),
    )


#: (notificationType, subtype) -> tip normalizat; subtype gol = orice subtype.
APPLE_NOTIFICATION_MAP: dict[tuple[str, str], WebhookEventType] = {
    ("SUBSCRIBED", ""): WebhookEventType.SUBSCRIPTION_CREATED,
    ("DID_RENEW", ""): WebhookEventType.SUBSCRIPTION_RENEWED,
    ("DID_FAIL_TO_RENEW", ""): WebhookEventType.SUBSCRIPTION_PAYMENT_FAILED,
    ("GRACE_PERIOD_INITIATED", ""): WebhookEventType.SUBSCRIPTION_PAYMENT_FAILED,
    ("EXPIRED", ""): WebhookEventType.SUBSCRIPTION_EXPIRED,
    ("DID_CHANGE_RENEWAL_STATUS", "AUTO_RENEW_DISABLED"): WebhookEventType.SUBSCRIPTION_CANCELLED,
    ("DID_CHANGE_RENEWAL_STATUS", ""): WebhookEventType.SUBSCRIPTION_UPDATED,
    ("DID_CHANGE_RENEWAL_PREF", ""): WebhookEventType.SUBSCRIPTION_UPDATED,
    ("PRICE_INCREASE", ""): WebhookEventType.SUBSCRIPTION_UPDATED,
    ("RENEWAL_EXTENDED", ""): WebhookEventType.SUBSCRIPTION_UPDATED,
    ("REFUND", ""): WebhookEventType.PURCHASE_REFUNDED,
    ("REVOKE", ""): WebhookEventType.PURCHASE_REFUNDED,
}


def webhook_event_from_apple(decoded: dict, transaction: dict, renewal: dict) -> WebhookEvent:
    kind = decoded.get("notificationType", "")
    subtype = decoded.get("subtype", "") or ""
    event_type = APPLE_NOTIFICATION_MAP.get((kind, subtype)) or APPLE_NOTIFICATION_MAP.get((kind, "")) or WebhookEventType.UNKNOWN
    data = decoded.get("data") or {}
    expires_ms = transaction.get("expiresDate")
    signed_ms = decoded.get("signedDate")
    return WebhookEvent(
        event_id=decoded.get("notificationUUID", ""),
        event_type=event_type,
        provider=PROVIDER,
        provider_event_type=f"{kind}/{subtype}" if subtype else kind,
        payload={
            "original_transaction_id": str(transaction.get("originalTransactionId", "")),
            "transaction_id": str(transaction.get("transactionId", "")),
            "product_id": transaction.get("productId", ""),
            "bundle_id": data.get("bundleId", "") or transaction.get("bundleId", ""),
            "environment": data.get("environment", ""),
            "expires_at": datetime.fromtimestamp(expires_ms / 1000, tz=UTC).isoformat() if expires_ms else None,
            "auto_renew": renewal.get("autoRenewStatus") == 1 if "autoRenewStatus" in renewal else None,
            "status": data.get("status"),
            "revocation_reason": transaction.get("revocationReason"),
        },
        idempotency_key=decoded.get("notificationUUID", ""),
        received_at=datetime.fromtimestamp(signed_ms / 1000, tz=UTC) if signed_ms else datetime.now(UTC),
        extra={"notification_type": kind, "subtype": subtype, "version": decoded.get("version", "")},
        provider_meta=_meta({"decoded": decoded, "transaction": transaction, "renewal": renewal}, decoded.get("notificationUUID", "")),
    )
