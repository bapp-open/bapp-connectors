"""PayPal <-> DTO mappers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    CheckoutSession,
    FinancialTransaction,
    FinancialTransactionType,
    PaginatedResult,
    PaymentMethodType,
    PaymentResult,
    ProviderMeta,
    Refund,
    WebhookEvent,
    WebhookEventType,
)


def _find_approval_url(links: list[dict]) -> str:
    """Extract the approval URL from PayPal HATEOAS links."""
    for link in links:
        if link.get("rel") == "approve":
            return link.get("href", "")
    return ""


def checkout_session_from_paypal(response: dict) -> CheckoutSession:
    links = response.get("links", [])
    approval_url = _find_approval_url(links)

    purchase_units = response.get("purchase_units", [])
    amount_data = purchase_units[0].get("amount", {}) if purchase_units else {}

    return CheckoutSession(
        session_id=response.get("id", ""),
        payment_url=approval_url,
        amount=Decimal(str(amount_data.get("value", 0))),
        currency=amount_data.get("currency_code", ""),
        extra={"paypal_order_id": response.get("id", ""), "status": response.get("status", "")},
        provider_meta=ProviderMeta(
            provider="paypal",
            raw_id=response.get("id", ""),
            raw_payload=response,
            fetched_at=datetime.now(UTC),
        ),
    )


PAYPAL_STATUS_MAP = {
    "COMPLETED": "approved",
    "APPROVED": "approved",
    "CREATED": "pending",
    "SAVED": "pending",
    "PAYER_ACTION_REQUIRED": "pending",
    "VOIDED": "cancelled",
}


def payment_result_from_paypal(response: dict) -> PaymentResult:
    raw_status = response.get("status", "")
    status = PAYPAL_STATUS_MAP.get(raw_status, raw_status.lower())

    purchase_units = response.get("purchase_units", [])
    amount_data = purchase_units[0].get("amount", {}) if purchase_units else {}
    custom_id = purchase_units[0].get("custom_id", "") if purchase_units else ""

    return PaymentResult(
        payment_id=response.get("id", ""),
        status=status,
        amount=Decimal(str(amount_data.get("value", 0))),
        currency=amount_data.get("currency_code", ""),
        method=PaymentMethodType.WALLET,
        extra={
            "paypal_status": raw_status,
            "custom_id": custom_id,
        },
        provider_meta=ProviderMeta(
            provider="paypal",
            raw_id=response.get("id", ""),
            raw_payload=response,
            fetched_at=datetime.now(UTC),
        ),
    )


def refund_from_paypal(response: dict, capture_id: str) -> Refund:
    amount_data = response.get("amount", {})
    return Refund(
        refund_id=response.get("id", ""),
        payment_id=capture_id,
        amount=Decimal(str(amount_data.get("value", 0))),
        currency=amount_data.get("currency_code", ""),
        status=response.get("status", "").lower(),
        extra={"paypal_status": response.get("status", "")},
        provider_meta=ProviderMeta(
            provider="paypal",
            raw_id=response.get("id", ""),
            raw_payload=response,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Financial / Reporting mappers ──

# PayPal transaction type codes
# https://developer.paypal.com/docs/transaction-search/transaction-event-codes/
PAYPAL_TX_TYPE_MAP: dict[str, FinancialTransactionType] = {
    "T0000": FinancialTransactionType.SALE,       # General: orders, payments
    "T0001": FinancialTransactionType.SALE,       # Website payment
    "T0002": FinancialTransactionType.SALE,       # Subscription payment
    "T0003": FinancialTransactionType.SALE,       # Preapproved payment
    "T0006": FinancialTransactionType.PAYMENT,    # Payout/withdrawal
    "T0007": FinancialTransactionType.SALE,       # Checkout API
    "T0400": FinancialTransactionType.REFUND,     # General refund
    "T1106": FinancialTransactionType.PAYMENT,    # Payment reversal
    "T1107": FinancialTransactionType.REFUND,     # Payment refund
    "T1201": FinancialTransactionType.REFUND,     # Chargeback
    "T0800": FinancialTransactionType.COMMISSION, # PayPal fee
    "T0803": FinancialTransactionType.COMMISSION, # Fee reversal
    "T9800": FinancialTransactionType.PAYMENT,    # Bank transfer/withdrawal
}


def _parse_paypal_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    # PayPal uses ISO 8601 with timezone: "2026-01-15T10:30:00+0000"
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).astimezone(UTC)
        except ValueError:
            continue
    return None


def transaction_from_paypal(data: dict) -> FinancialTransaction:
    """Map a PayPal reporting transaction to a normalized FinancialTransaction."""
    tx_info = data.get("transaction_info", {})
    payer_info = data.get("payer_info", {})
    payer_name = payer_info.get("payer_name", {})

    amount_data = tx_info.get("transaction_amount", {})
    fee_data = tx_info.get("fee_amount", {})

    amount = Decimal(str(amount_data.get("value", 0)))
    fee = Decimal(str(fee_data.get("value", 0))) if fee_data.get("value") else None
    currency = amount_data.get("currency_code", "")

    raw_type = tx_info.get("transaction_event_code", "")
    # Use first 5 chars for category lookup (e.g. T0006)
    tx_type = PAYPAL_TX_TYPE_MAP.get(raw_type[:5], FinancialTransactionType.OTHER)

    customer_name = ""
    if payer_name:
        first = payer_name.get("given_name") or payer_name.get("alternate_full_name", "")
        last = payer_name.get("surname", "")
        customer_name = f"{first} {last}".strip() if first or last else payer_name.get("alternate_full_name", "")

    debit = abs(amount) if amount < 0 else Decimal("0")
    credit = amount if amount > 0 else Decimal("0")

    return FinancialTransaction(
        transaction_id=tx_info.get("transaction_id", ""),
        transaction_type=tx_type,
        raw_transaction_type=raw_type,
        transaction_date=_parse_paypal_datetime(tx_info.get("transaction_initiation_date")),
        description=tx_info.get("transaction_subject") or tx_info.get("transaction_note") or "",
        currency=currency,
        debit=debit,
        credit=credit,
        net_amount=amount,
        commission_amount=abs(Decimal(str(fee))) if fee else None,
        invoice_number=tx_info.get("invoice_id", ""),
        payment_date=_parse_paypal_datetime(tx_info.get("transaction_updated_date")),
        provider_meta=ProviderMeta(
            provider="paypal",
            raw_id=tx_info.get("transaction_id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v for k, v in {
                "customer_name": customer_name,
                "customer_email": payer_info.get("email_address"),
                "payer_id": payer_info.get("account_id"),
                "custom_field": tx_info.get("custom_field"),
                "protection_eligibility": tx_info.get("protection_eligibility"),
            }.items()
            if v
        },
    )


def transactions_from_paypal(response: dict) -> PaginatedResult[FinancialTransaction]:
    """Map PayPal reporting/transactions response to PaginatedResult."""
    tx_details = response.get("transaction_details", [])
    items = [transaction_from_paypal(td) for td in tx_details]

    total_items = response.get("total_items")
    total_pages = response.get("total_pages")
    page = response.get("page")

    has_more = False
    if total_pages is not None and page is not None:
        has_more = int(page) < int(total_pages)

    return PaginatedResult(
        items=items,
        has_more=has_more,
        cursor=str(int(page) + 1) if has_more else None,
        total=int(total_items) if total_items is not None else None,
    )


WEBHOOK_EVENT_MAP = {
    "CHECKOUT.ORDER.APPROVED": WebhookEventType.PAYMENT_COMPLETED,
    "PAYMENT.CAPTURE.COMPLETED": WebhookEventType.PAYMENT_COMPLETED,
    "PAYMENT.CAPTURE.DENIED": WebhookEventType.PAYMENT_FAILED,
}


def webhook_event_from_paypal(webhook_data: dict) -> WebhookEvent:
    event_type_str = webhook_data.get("event_type", "")
    event_type = WEBHOOK_EVENT_MAP.get(event_type_str, WebhookEventType.UNKNOWN)

    resource = webhook_data.get("resource", {})
    purchase_units = resource.get("purchase_units", [])
    custom_id = ""
    if purchase_units:
        custom_id = purchase_units[0].get("custom_id", "")

    return WebhookEvent(
        event_id=webhook_data.get("id", ""),
        event_type=event_type,
        provider="paypal",
        provider_event_type=event_type_str,
        payload=webhook_data,
        idempotency_key=webhook_data.get("id", ""),
        received_at=datetime.now(UTC),
        extra={"custom_id": custom_id, "resource_id": resource.get("id", "")},
    )
