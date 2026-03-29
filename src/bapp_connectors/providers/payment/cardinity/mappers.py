"""Cardinity <-> DTO mappers."""

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


def checkout_session_from_cardinity(form_data: dict, form_url: str) -> CheckoutSession:
    return CheckoutSession(
        session_id=form_data.get("order_id", ""),
        payment_url=form_url,
        amount=Decimal(str(form_data.get("amount", 0))),
        currency=form_data.get("currency", "EUR"),
        description=form_data.get("description", ""),
        extra={"form_data": form_data, "form_action": form_url},
        provider_meta=ProviderMeta(
            provider="cardinity",
            raw_id=form_data.get("order_id", ""),
            raw_payload=form_data,
            fetched_at=datetime.now(UTC),
        ),
    )


STATUS_MAP = {
    "approved": "approved",
    "pending": "pending",
    "declined": "declined",
}


def payment_result_from_cardinity(post_data: dict) -> PaymentResult:
    raw_status = post_data.get("status", "")
    status = STATUS_MAP.get(raw_status, f"unknown_{raw_status}")

    return PaymentResult(
        payment_id=post_data.get("id", post_data.get("order_id", "")),
        status=status,
        amount=Decimal(str(post_data.get("amount", 0))) if post_data.get("amount") else Decimal(0),
        currency=post_data.get("currency", ""),
        method=PaymentMethodType.CARD,
        extra={
            "order_id": post_data.get("order_id", ""),
            "cardinity_status": raw_status,
        },
        provider_meta=ProviderMeta(
            provider="cardinity",
            raw_id=post_data.get("id", ""),
            raw_payload=post_data,
            fetched_at=datetime.now(UTC),
        ),
    )


WEBHOOK_EVENT_MAP = {
    "approved": WebhookEventType.ORDER_UPDATED,
    "declined": WebhookEventType.UNKNOWN,
    "pending": WebhookEventType.UNKNOWN,
}


def webhook_event_from_cardinity(post_data: dict) -> WebhookEvent:
    raw_status = post_data.get("status", "")
    event_type = WEBHOOK_EVENT_MAP.get(raw_status, WebhookEventType.UNKNOWN)

    return WebhookEvent(
        event_id=post_data.get("id", post_data.get("order_id", "")),
        event_type=event_type,
        provider="cardinity",
        provider_event_type=f"payment.{raw_status}",
        payload=post_data,
        idempotency_key=post_data.get("id", ""),
        received_at=datetime.now(UTC),
    )
