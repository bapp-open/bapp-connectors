"""
Netopia <-> DTO mappers.

Converts between raw Netopia API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    CheckoutSession,
    PaymentMethodType,
    PaymentResult,
    ProviderMeta,
    Refund,
    WebhookEvent,
    WebhookEventType,
)

# ── Status mappings ──

# Purchase statuses from the official SDK (netopiapayments/composer, IPN.php).
NETOPIA_STATUS_MAP: dict[int, str] = {
    1: "new",
    2: "opened",  # pre-authorized, not captured
    3: "paid",  # captured
    4: "canceled",  # voided
    5: "confirmed",
    6: "pending",
    7: "scheduled",
    8: "credit",  # captured, then refunded
    9: "chargeback_init",
    10: "chargeback_accept",
    11: "error",
    12: "declined",
    13: "fraud",  # held for review
    14: "pending_auth",
    15: "3d_auth",  # customer must complete 3-D Secure
    16: "chargeback_representment",
    17: "reversed",
    18: "pending_any",
    19: "programmed_recurrent_payment",
    20: "canceled_programmed_recurrent_payment",
    21: "trial_pending",
    22: "trial",
    23: "expired",  # never paid
}

NETOPIA_STATUS_FRIENDLY: dict[str, str] = {
    "new": "pending",
    "opened": "authorized",
    "paid": "completed",
    "canceled": "cancelled",
    "confirmed": "completed",
    "pending": "pending",
    "scheduled": "pending",
    "credit": "refunded",
    "chargeback_init": "disputed",
    "chargeback_accept": "refunded",
    "error": "failed",
    "declined": "failed",
    "fraud": "processing",
    "pending_auth": "processing",
    "3d_auth": "pending",
    "chargeback_representment": "disputed",
    "reversed": "cancelled",
    "pending_any": "pending",
    "programmed_recurrent_payment": "pending",
    "canceled_programmed_recurrent_payment": "cancelled",
    "trial_pending": "pending",
    "trial": "pending",
    "expired": "cancelled",
}


def netopia_status(data: dict) -> tuple[int | None, str, str]:
    """Return (code, raw name, normalized status).

    Netopia puts the status in ``payment.status``; a top-level ``status`` is
    only a fallback for older payload shapes.
    """
    payment = data.get("payment") or {}
    code = payment.get("status") if isinstance(payment.get("status"), int) else data.get("status")
    raw = NETOPIA_STATUS_MAP.get(code, "unknown") if isinstance(code, int) else str(code or "unknown")
    return code if isinstance(code, int) else None, raw, NETOPIA_STATUS_FRIENDLY.get(raw, raw)


# ── Checkout Session mapper ──


def checkout_session_from_netopia(data: dict, amount: Decimal, currency: str, description: str) -> CheckoutSession:
    """Map a Netopia start payment response to a normalized CheckoutSession DTO."""
    payment = data.get("payment", {})
    payment_url = payment.get("paymentURL", "")

    ntp_id = payment.get("ntpID") or data.get("order", {}).get("ntpID", "")
    session_id = ntp_id or ""

    return CheckoutSession(
        session_id=session_id,
        payment_url=payment_url,
        amount=amount,
        currency=currency.upper(),
        description=description,
        extra={
            "ntp_id": ntp_id,
            "status": data.get("status"),
        },
        provider_meta=ProviderMeta(
            provider="netopia",
            raw_id=session_id,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Payment result mapper ──


def payment_from_netopia(data: dict) -> PaymentResult:
    """Map a Netopia payment status response to a normalized PaymentResult DTO."""
    status_code, raw_status, normalized_status = netopia_status(data)

    payment = data.get("payment") or {}
    order = data.get("order") or {}
    amount = Decimal(str(payment.get("amount") or order.get("amount") or 0))
    currency = (payment.get("currency") or order.get("currency") or "RON").upper()
    ntp_id = payment.get("ntpID") or order.get("ntpID") or data.get("ntpID", "")

    paid_at = None
    if normalized_status == "completed":
        paid_at = datetime.now(UTC)

    return PaymentResult(
        payment_id=str(ntp_id),
        status=normalized_status,
        amount=amount,
        currency=currency,
        method=PaymentMethodType.CARD,
        paid_at=paid_at,
        extra={
            "netopia_status_code": status_code,
            "netopia_status": raw_status,
        },
        provider_meta=ProviderMeta(
            provider="netopia",
            raw_id=str(ntp_id),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Refund mapper ──


def refund_from_netopia(data: dict, payment_id: str, requested_amount: Decimal | None = None) -> Refund:
    """Map a Netopia credit response to a normalized Refund DTO.

    Call only after ``raise_for_netopia_error``: a refused credit never reaches
    here. The response has no ``order``; the refunded amount is what was asked
    for, else what Netopia reports on ``payment``.
    """
    payment = data.get("payment") or {}
    status_code, raw_status, normalized_status = netopia_status(data)
    if requested_amount is not None:
        amount = Decimal(str(requested_amount))
    else:
        amount = Decimal(str(payment.get("amount") or 0))
    currency = (payment.get("currency") or "RON").upper()
    ntp_id = payment.get("ntpID") or data.get("ntpID") or payment_id

    return Refund(
        refund_id=str(ntp_id),
        payment_id=payment_id,
        amount=amount,
        currency=currency,
        reason="",
        status="completed",
        created_at=datetime.now(UTC),
        extra={
            "netopia_status_code": status_code,
            "netopia_status": raw_status,
            "payment_status": normalized_status,
        },
        provider_meta=ProviderMeta(
            provider="netopia",
            raw_id=str(ntp_id),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Webhook event mapper ──


NETOPIA_IPN_EVENT_MAP: dict[str, WebhookEventType] = {
    "pending": WebhookEventType.PAYMENT_PENDING,
    "processing": WebhookEventType.PAYMENT_PENDING,
    "authorized": WebhookEventType.PAYMENT_PENDING,
    "completed": WebhookEventType.PAYMENT_COMPLETED,
    "failed": WebhookEventType.PAYMENT_FAILED,
    "cancelled": WebhookEventType.PAYMENT_FAILED,
    "refunded": WebhookEventType.PAYMENT_REFUNDED,
}


def webhook_event_from_netopia(data: dict) -> WebhookEvent:
    """Map a Netopia IPN notification to a WebhookEvent DTO."""
    status_code, raw_status, normalized_status = netopia_status(data)
    event_type = NETOPIA_IPN_EVENT_MAP.get(normalized_status, WebhookEventType.UNKNOWN)

    payment = data.get("payment") or {}
    order = data.get("order") or {}
    ntp_id = payment.get("ntpID") or order.get("ntpID") or data.get("ntpID", "")
    confirmed = None
    if normalized_status == "completed":
        confirmed = payment_from_netopia(data).model_copy(
            update={"reference": str(order.get("orderID") or ""), "provider_meta": None}
        )

    return WebhookEvent(
        event_id=str(ntp_id),
        event_type=event_type,
        provider="netopia",
        provider_event_type=f"payment.{raw_status}",
        payload=data,
        # One payment gets several IPNs (paid, then refunded); keying on the
        # ntpID alone dropped the later ones as duplicates. The normalized
        # status keeps "paid" (3) and "confirmed" (5) as one completion.
        idempotency_key=f"{ntp_id}:{normalized_status}",
        received_at=datetime.now(UTC),
        payment=confirmed,
    )
