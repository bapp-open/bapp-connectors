"""
EuPlatesc <-> DTO mappers.

EuPlatesc is form-based — no REST API for querying.
- Checkout: build form data → redirect customer
- IPN: POST notification with payment result → verify HMAC → extract result
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    CheckoutSession,
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
