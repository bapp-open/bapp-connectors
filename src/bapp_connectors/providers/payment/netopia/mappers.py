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
)

# ── Status mappings ──

NETOPIA_STATUS_MAP: dict[int, str] = {
    0: "pending",
    3: "paid_pending",
    5: "confirmed",
    12: "cancelled",
    15: "credit",  # refunded
}

NETOPIA_STATUS_FRIENDLY: dict[str, str] = {
    "pending": "pending",
    "paid_pending": "processing",
    "confirmed": "completed",
    "cancelled": "cancelled",
    "credit": "refunded",
}


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
    status_code = data.get("status")
    raw_status = (
        NETOPIA_STATUS_MAP.get(status_code, "unknown")
        if isinstance(status_code, int)
        else str(status_code or "unknown")
    )
    normalized_status = NETOPIA_STATUS_FRIENDLY.get(raw_status, raw_status)

    payment = data.get("payment", {})
    order = data.get("order", {})
    amount = Decimal(str(order.get("amount", 0)))
    currency = (order.get("currency") or "RON").upper()
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


def refund_from_netopia(data: dict, payment_id: str) -> Refund:
    """Map a Netopia refund/credit response to a normalized Refund DTO."""
    order = data.get("order", {})
    amount = Decimal(str(order.get("amount", 0)))
    currency = (order.get("currency") or "RON").upper()
    ntp_id = data.get("payment", {}).get("ntpID") or data.get("ntpID", "")

    return Refund(
        refund_id=str(ntp_id),
        payment_id=payment_id,
        amount=amount,
        currency=currency,
        reason="",
        status="completed",
        created_at=datetime.now(UTC),
        extra={
            "netopia_status": data.get("status"),
        },
        provider_meta=ProviderMeta(
            provider="netopia",
            raw_id=str(ntp_id),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )
