"""
Stripe <-> DTO mappers.

Converts between raw Stripe API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    CardBrand,
    CheckoutSession,
    FinancialTransaction,
    FinancialTransactionType,
    PaginatedResult,
    PaymentMethodType,
    PaymentResult,
    ProviderMeta,
    Refund,
    SavedPaymentMethod,
    Subscription,
    SubscriptionInterval,
    SubscriptionStatus,
    WebhookEvent,
    WebhookEventType,
)

# ── Amount helpers ──
# Stripe uses smallest currency unit (cents), so we convert to/from Decimal.

ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "bif",
        "clp",
        "djf",
        "gnf",
        "jpy",
        "kmf",
        "krw",
        "mga",
        "pyg",
        "rwf",
        "ugx",
        "vnd",
        "vuv",
        "xaf",
        "xof",
        "xpf",
    }
)


def amount_to_stripe(amount: Decimal, currency: str) -> int:
    """Convert a Decimal amount to Stripe's smallest currency unit (cents)."""
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return int(amount)
    return int(amount * 100)


def amount_from_stripe(amount_minor: int, currency: str) -> Decimal:
    """Convert Stripe's smallest currency unit back to a Decimal."""
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return Decimal(str(amount_minor))
    return Decimal(str(amount_minor)) / Decimal("100")


# ── Checkout Session mapper ──


def checkout_session_from_stripe(data: dict) -> CheckoutSession:
    """Map a Stripe checkout session response to a normalized CheckoutSession DTO."""
    currency = (data.get("currency") or "").upper()
    amount_total = data.get("amount_total") or 0

    expires_at = None
    if ts := data.get("expires_at"):
        expires_at = datetime.fromtimestamp(ts, tz=UTC)

    return CheckoutSession(
        session_id=data.get("id", ""),
        payment_url=data.get("url") or "",
        amount=amount_from_stripe(amount_total, currency),
        currency=currency,
        description=data.get("metadata", {}).get("identifier", ""),
        expires_at=expires_at,
        extra={
            "payment_intent": data.get("payment_intent"),
            "status": data.get("status"),
            "customer_email": data.get("customer_email"),
        },
        provider_meta=ProviderMeta(
            provider="stripe",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Payment Intent mapper ──

STRIPE_STATUS_MAP: dict[str, str] = {
    "requires_payment_method": "pending",
    "requires_confirmation": "pending",
    "requires_action": "pending",
    "processing": "processing",
    "requires_capture": "authorized",
    "canceled": "cancelled",
    "succeeded": "completed",
}

# Reverse: normalized status -> primary Stripe status (for list_payments filtering)
NORMALIZED_TO_STRIPE_STATUS: dict[str, str] = {
    "completed": "succeeded",
    "cancelled": "canceled",
    "processing": "processing",
    "pending": "requires_payment_method",
    "authorized": "requires_capture",
}

STRIPE_METHOD_MAP: dict[str, PaymentMethodType] = {
    "card": PaymentMethodType.CARD,
    "bank_transfer": PaymentMethodType.BANK_TRANSFER,
    "sepa_debit": PaymentMethodType.BANK_TRANSFER,
}


def payment_from_stripe(data: dict) -> PaymentResult:
    """Map a Stripe payment intent response to a normalized PaymentResult DTO."""
    currency = (data.get("currency") or "").upper()
    amount = data.get("amount") or 0
    raw_status = data.get("status", "")

    methods = data.get("payment_method_types", [])
    method = STRIPE_METHOD_MAP.get(methods[0], PaymentMethodType.OTHER) if methods else None

    paid_at = None
    if raw_status == "succeeded" and (ts := data.get("created")):
        paid_at = datetime.fromtimestamp(ts, tz=UTC)

    return PaymentResult(
        payment_id=data.get("id", ""),
        status=STRIPE_STATUS_MAP.get(raw_status, raw_status),
        amount=amount_from_stripe(amount, currency),
        currency=currency,
        method=method,
        paid_at=paid_at,
        extra={
            "stripe_status": raw_status,
            "latest_charge": data.get("latest_charge"),
            "metadata": data.get("metadata", {}),
        },
        provider_meta=ProviderMeta(
            provider="stripe",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Refund mapper ──


def refund_from_stripe(data: dict) -> Refund:
    """Map a Stripe refund response to a normalized Refund DTO."""
    currency = (data.get("currency") or "").upper()
    amount = data.get("amount") or 0

    created_at = None
    if ts := data.get("created"):
        created_at = datetime.fromtimestamp(ts, tz=UTC)

    return Refund(
        refund_id=data.get("id", ""),
        payment_id=data.get("payment_intent") or "",
        amount=amount_from_stripe(amount, currency),
        currency=currency,
        reason=data.get("reason") or "",
        status=data.get("status", ""),
        created_at=created_at,
        extra={
            "metadata": data.get("metadata", {}),
        },
        provider_meta=ProviderMeta(
            provider="stripe",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Subscription mapper ──

STRIPE_SUBSCRIPTION_STATUS_MAP: dict[str, SubscriptionStatus] = {
    "active": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "paused": SubscriptionStatus.PAUSED,
    "incomplete": SubscriptionStatus.PENDING,
    "incomplete_expired": SubscriptionStatus.CANCELLED,
    "canceled": SubscriptionStatus.CANCELLED,
    "unpaid": SubscriptionStatus.UNPAID,
    "trialing": SubscriptionStatus.TRIALING,
}

STRIPE_INTERVAL_MAP: dict[str, SubscriptionInterval] = {
    "day": SubscriptionInterval.DAY,
    "week": SubscriptionInterval.WEEK,
    "month": SubscriptionInterval.MONTH,
    "year": SubscriptionInterval.YEAR,
}


def subscription_from_stripe(data: dict) -> Subscription:
    """Map a Stripe subscription response to a normalized Subscription DTO."""
    currency = (data.get("currency") or "").upper()
    items = data.get("items", {}).get("data", [])

    # Extract amount and interval from the first subscription item
    amount = Decimal("0")
    interval = SubscriptionInterval.MONTH
    interval_count = 1
    price_id = ""
    if items:
        price = items[0].get("price", {})
        price_id = price.get("id", "")
        amount_minor = price.get("unit_amount") or 0
        amount = amount_from_stripe(amount_minor, currency)
        recurring = price.get("recurring", {})
        interval = STRIPE_INTERVAL_MAP.get(
            recurring.get("interval", "month"), SubscriptionInterval.MONTH,
        )
        interval_count = recurring.get("interval_count", 1)

    raw_status = data.get("status", "")

    cancelled_at = None
    if ts := data.get("canceled_at"):
        cancelled_at = datetime.fromtimestamp(ts, tz=UTC)

    trial_start = None
    if ts := data.get("trial_start"):
        trial_start = datetime.fromtimestamp(ts, tz=UTC)

    trial_end = None
    if ts := data.get("trial_end"):
        trial_end = datetime.fromtimestamp(ts, tz=UTC)

    created_at = None
    if ts := data.get("created"):
        created_at = datetime.fromtimestamp(ts, tz=UTC)

    current_period_start = None
    if ts := data.get("current_period_start"):
        current_period_start = datetime.fromtimestamp(ts, tz=UTC)

    current_period_end = None
    if ts := data.get("current_period_end"):
        current_period_end = datetime.fromtimestamp(ts, tz=UTC)

    return Subscription(
        subscription_id=data.get("id", ""),
        status=STRIPE_SUBSCRIPTION_STATUS_MAP.get(raw_status, SubscriptionStatus.PENDING),
        customer_id=data.get("customer") or "",
        price_id=price_id,
        amount=amount,
        currency=currency,
        interval=interval,
        interval_count=interval_count,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=data.get("cancel_at_period_end", False),
        cancelled_at=cancelled_at,
        trial_start=trial_start,
        trial_end=trial_end,
        created_at=created_at,
        extra={"metadata": data.get("metadata", {})},
        provider_meta=ProviderMeta(
            provider="stripe",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Payment Method mapper ──

STRIPE_CARD_BRAND_MAP: dict[str, CardBrand] = {
    "visa": CardBrand.VISA,
    "mastercard": CardBrand.MASTERCARD,
    "amex": CardBrand.AMEX,
    "discover": CardBrand.DISCOVER,
    "diners": CardBrand.DINERS,
    "jcb": CardBrand.JCB,
    "unionpay": CardBrand.UNIONPAY,
}


def payment_method_from_stripe(data: dict, default_pm_id: str = "") -> SavedPaymentMethod:
    """Map a Stripe PaymentMethod response to a normalized SavedPaymentMethod DTO."""
    pm_type = data.get("type", "card")
    card = data.get("card", {})

    method_type = STRIPE_METHOD_MAP.get(pm_type, PaymentMethodType.OTHER)
    brand = STRIPE_CARD_BRAND_MAP.get(card.get("brand", ""), CardBrand.UNKNOWN)

    created_at = None
    if ts := data.get("created"):
        created_at = datetime.fromtimestamp(ts, tz=UTC)

    return SavedPaymentMethod(
        payment_method_id=data.get("id", ""),
        customer_id=data.get("customer") or "",
        method_type=method_type,
        card_brand=brand,
        last_four=card.get("last4", ""),
        expiry_month=card.get("exp_month"),
        expiry_year=card.get("exp_year"),
        is_default=data.get("id", "") == default_pm_id,
        created_at=created_at,
        extra={
            "fingerprint": card.get("fingerprint", ""),
            "funding": card.get("funding", ""),
            "country": card.get("country", ""),
        },
        provider_meta=ProviderMeta(
            provider="stripe",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Webhook mapper ──

STRIPE_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    # One-off payments
    "checkout.session.completed": WebhookEventType.PAYMENT_COMPLETED,
    "payment_intent.succeeded": WebhookEventType.PAYMENT_COMPLETED,
    "charge.succeeded": WebhookEventType.PAYMENT_COMPLETED,
    "payment_intent.payment_failed": WebhookEventType.PAYMENT_FAILED,
    "charge.refunded": WebhookEventType.PAYMENT_REFUNDED,
    # Subscriptions
    "customer.subscription.created": WebhookEventType.SUBSCRIPTION_CREATED,
    "customer.subscription.updated": WebhookEventType.SUBSCRIPTION_UPDATED,
    "customer.subscription.deleted": WebhookEventType.SUBSCRIPTION_CANCELLED,
    # Subscription invoices (recurring payment success/failure)
    "invoice.payment_succeeded": WebhookEventType.SUBSCRIPTION_PAYMENT_SUCCEEDED,
    "invoice.payment_failed": WebhookEventType.SUBSCRIPTION_PAYMENT_FAILED,
}


# ── Financial / Payout mappers ──

STRIPE_BALANCE_TX_TYPE_MAP: dict[str, FinancialTransactionType] = {
    "charge": FinancialTransactionType.SALE,
    "payment": FinancialTransactionType.SALE,
    "refund": FinancialTransactionType.REFUND,
    "adjustment": FinancialTransactionType.OTHER,
    "payout": FinancialTransactionType.PAYMENT,
    "stripe_fee": FinancialTransactionType.COMMISSION,
    "application_fee": FinancialTransactionType.COMMISSION,
}


def transaction_from_stripe_balance(data: dict) -> FinancialTransaction:
    """Map a Stripe balance_transaction to a normalized FinancialTransaction."""
    currency = (data.get("currency") or "").upper()
    amount = amount_from_stripe(data.get("amount", 0), currency)
    fee = amount_from_stripe(data.get("fee", 0), currency)
    net = amount_from_stripe(data.get("net", 0), currency)

    raw_type = data.get("type", "")
    tx_type = STRIPE_BALANCE_TX_TYPE_MAP.get(raw_type, FinancialTransactionType.OTHER)

    created_at = None
    if ts := data.get("created"):
        created_at = datetime.fromtimestamp(ts, tz=UTC)

    # Extract billing details from expanded source (charge)
    source = data.get("source")
    customer_name = ""
    customer_email = ""
    customer_vat_id = ""
    description = data.get("description") or ""

    if isinstance(source, dict):
        billing = source.get("billing_details") or {}
        customer_name = billing.get("name") or ""
        customer_email = billing.get("email") or ""
        description = description or source.get("description") or ""

        # Customer tax IDs from expanded customer
        customer = source.get("customer")
        if isinstance(customer, dict):
            customer_name = customer_name or customer.get("name") or ""
            customer_email = customer_email or customer.get("email") or ""
            tax_ids = customer.get("tax_ids", {}).get("data", [])
            if tax_ids:
                customer_vat_id = tax_ids[0].get("value", "")

    debit = abs(amount) if amount < 0 else Decimal("0")
    credit = amount if amount > 0 else Decimal("0")

    return FinancialTransaction(
        transaction_id=data.get("id", ""),
        transaction_type=tx_type,
        raw_transaction_type=raw_type,
        transaction_date=created_at,
        description=description,
        currency=currency,
        debit=debit,
        credit=credit,
        net_amount=net,
        commission_amount=fee if fee else None,
        invoice_number=data.get("source", "") if isinstance(data.get("source"), str) else "",
        provider_meta=ProviderMeta(
            provider="stripe",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v for k, v in {
                "customer_name": customer_name,
                "customer_email": customer_email,
                "customer_vat_id": customer_vat_id,
                "fee": str(fee),
                "fee_details": data.get("fee_details"),
                "source_id": data.get("source") if isinstance(data.get("source"), str) else None,
                "payout_id": data.get("payout") if isinstance(data.get("payout"), str) else None,
            }.items()
            if v
        },
    )


def transactions_from_stripe_balance(response: dict) -> PaginatedResult[FinancialTransaction]:
    """Map Stripe balance_transactions list to PaginatedResult."""
    items = [transaction_from_stripe_balance(bt) for bt in response.get("data", [])]
    has_more = response.get("has_more", False)
    return PaginatedResult(
        items=items,
        has_more=has_more,
        cursor=items[-1].transaction_id if items and has_more else None,
        total=None,
    )


def webhook_event_from_stripe(data: dict) -> WebhookEvent:
    """Map a Stripe webhook event to a normalized WebhookEvent DTO."""
    raw_type = data.get("type", "")
    event_type = STRIPE_WEBHOOK_EVENT_MAP.get(raw_type, WebhookEventType.UNKNOWN)

    return WebhookEvent(
        event_id=data.get("id", ""),
        event_type=event_type,
        provider="stripe",
        provider_event_type=raw_type,
        payload=data.get("data", {}).get("object", {}),
        idempotency_key=data.get("id", ""),
        received_at=datetime.now(UTC),
        extra={
            "api_version": data.get("api_version"),
            "livemode": data.get("livemode"),
        },
        provider_meta=ProviderMeta(
            provider="stripe",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )
