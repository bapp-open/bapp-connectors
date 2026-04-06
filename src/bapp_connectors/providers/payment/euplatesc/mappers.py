"""
EuPlatesc <-> DTO mappers.

- Checkout: build form data → redirect customer
- IPN: POST notification with payment result → verify HMAC → extract result
- Management API: transaction queries, invoice listing, captures, refunds
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    CheckoutSession,
    FinancialInvoice,
    FinancialTransaction,
    FinancialTransactionType,
    PaginatedResult,
    PaymentMethodType,
    PaymentResult,
    ProviderMeta,
    WebhookEvent,
    WebhookEventType,
)

from .manifest import EUPLATESC_LIVE_URL


def checkout_session_from_euplatesc(form_data: dict) -> CheckoutSession:
    """Map EuPlatesc form data to a CheckoutSession DTO."""
    return CheckoutSession(
        session_id=form_data.get("invoice_id", ""),
        payment_url=EUPLATESC_LIVE_URL,
        amount=Decimal(str(form_data.get("amount", 0))),
        currency=form_data.get("curr", "RON"),
        description=form_data.get("order_desc", ""),
        extra={
            "form_data": form_data,
            "form_action": EUPLATESC_LIVE_URL,
        },
        provider_meta=ProviderMeta(
            provider="euplatesc",
            raw_id=form_data.get("invoice_id", ""),
            raw_payload=form_data,
            fetched_at=datetime.now(UTC),
        ),
    )


def payment_result_from_ipn(ipn_data: dict) -> PaymentResult:
    """Map an EuPlatesc IPN POST to a PaymentResult DTO."""
    action = ipn_data.get("action", "")
    status = "approved" if action == "0" else f"error_{action}"

    sec_status = ipn_data.get("sec_status", "")
    if sec_status and sec_status not in ("8", "9") and action == "0":
        status = "suspect"

    return PaymentResult(
        payment_id=ipn_data.get("ep_id", ""),
        status=status,
        amount=Decimal(str(ipn_data.get("amount", 0))),
        currency=ipn_data.get("curr", ""),
        method=PaymentMethodType.CARD,
        extra={
            "action": action,
            "message": ipn_data.get("message", ""),
            "approval": ipn_data.get("approval", ""),
            "sec_status": sec_status,
            "invoice_id": ipn_data.get("invoice_id", ""),
            "merch_id": ipn_data.get("merch_id", ""),
        },
        provider_meta=ProviderMeta(
            provider="euplatesc",
            raw_id=ipn_data.get("ep_id", ""),
            raw_payload=ipn_data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Financial / Invoice mappers ──


def _parse_ep_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        with contextlib.suppress(ValueError):
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
    return None


def invoice_from_euplatesc(data: dict) -> FinancialInvoice:
    """Map an EuPlatesc settlement invoice to a FinancialInvoice DTO."""
    return FinancialInvoice(
        invoice_number=data.get("invoice_number", data.get("number", "")),
        category=data.get("type", "settlement"),
        date=_parse_ep_date(data.get("date")),
        currency=data.get("currency", "RON"),
        total_amount=Decimal(str(data.get("amount", 0))) if data.get("amount") else Decimal("0"),
        provider_meta=ProviderMeta(
            provider="euplatesc",
            raw_id=data.get("invoice_number", data.get("number", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={k: v for k, v in data.items() if k not in ("invoice_number", "number", "date", "amount", "currency", "type")},
    )


def invoices_from_euplatesc(response: dict) -> PaginatedResult[FinancialInvoice]:
    """Map EuPlatesc INVOICES response to PaginatedResult."""
    items_raw = response.get("success", [])
    if isinstance(items_raw, str):
        return PaginatedResult(items=[], has_more=False, total=0)
    items = [invoice_from_euplatesc(inv) for inv in items_raw] if isinstance(items_raw, list) else []
    return PaginatedResult(items=items, has_more=False, total=len(items))


def transaction_from_euplatesc_invoice(data: dict) -> FinancialTransaction:
    """Map an EuPlatesc invoice transaction to a FinancialTransaction DTO."""
    amount = Decimal(str(data.get("amount", 0))) if data.get("amount") else Decimal("0")
    fee = Decimal(str(data.get("commission", data.get("fee", 0)))) if data.get("commission") or data.get("fee") else None

    return FinancialTransaction(
        transaction_id=str(data.get("ep_id", data.get("epid", ""))),
        transaction_type=FinancialTransactionType.SALE,
        raw_transaction_type=data.get("action", ""),
        transaction_date=_parse_ep_date(data.get("date", data.get("timestamp"))),
        description=data.get("description", ""),
        currency=data.get("currency", "RON"),
        debit=Decimal("0"),
        credit=amount,
        net_amount=amount - (fee or Decimal("0")),
        commission_amount=fee,
        order_id=data.get("invoice_id", ""),
        invoice_number=data.get("merch_invoice", ""),
        provider_meta=ProviderMeta(
            provider="euplatesc",
            raw_id=str(data.get("ep_id", data.get("epid", ""))),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v for k, v in data.items()
            if k not in ("ep_id", "epid", "amount", "commission", "fee", "date", "timestamp",
                         "currency", "action", "description", "invoice_id", "merch_invoice")
            and v
        },
    )


def transactions_from_euplatesc_invoice(response: dict) -> PaginatedResult[FinancialTransaction]:
    """Map EuPlatesc INVOICE transactions response to PaginatedResult."""
    items_raw = response.get("success", [])
    if isinstance(items_raw, str):
        return PaginatedResult(items=[], has_more=False, total=0)
    items = [transaction_from_euplatesc_invoice(tx) for tx in items_raw] if isinstance(items_raw, list) else []
    return PaginatedResult(items=items, has_more=False, total=len(items))


def webhook_event_from_euplatesc(ipn_data: dict) -> WebhookEvent:
    """Map an EuPlatesc IPN to a WebhookEvent DTO."""
    action = ipn_data.get("action", "")
    event_type = WebhookEventType.UNKNOWN
    if action == "0":
        event_type = WebhookEventType.ORDER_UPDATED  # payment confirmed

    return WebhookEvent(
        event_id=ipn_data.get("ep_id", ""),
        event_type=event_type,
        provider="euplatesc",
        provider_event_type=f"payment.action_{action}",
        payload=ipn_data,
        idempotency_key=ipn_data.get("ep_id", ""),
        received_at=datetime.now(UTC),
    )
