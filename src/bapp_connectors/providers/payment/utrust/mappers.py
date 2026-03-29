"""Utrust <-> DTO mappers."""

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

WEBHOOK_EVENT_MAP = {
    "ORDER.PAYMENT.RECEIVED": WebhookEventType.PAYMENT_COMPLETED,
    "ORDER.PAYMENT.CANCELLED": WebhookEventType.PAYMENT_FAILED,
}


def checkout_session_from_utrust(response: dict, reference: str, amount: Decimal, currency: str) -> CheckoutSession:
    redirect_url = ""
    try:
        redirect_url = response["data"]["attributes"]["redirect_url"]
    except (KeyError, TypeError):
        pass

    return CheckoutSession(
        session_id=reference,
        payment_url=redirect_url,
        amount=amount,
        currency=currency,
        extra={"api_response": response},
        provider_meta=ProviderMeta(
            provider="utrust",
            raw_id=reference,
            raw_payload=response,
            fetched_at=datetime.now(UTC),
        ),
    )


def payment_result_from_webhook(webhook_data: dict) -> PaymentResult:
    resource = webhook_data.get("resource", {})
    event_type = webhook_data.get("event_type", "")

    if event_type == "ORDER.PAYMENT.RECEIVED":
        status = "approved"
    elif event_type == "ORDER.PAYMENT.CANCELLED":
        status = "cancelled"
    else:
        status = f"unknown_{event_type}"

    return PaymentResult(
        payment_id=resource.get("reference", ""),
        status=status,
        amount=Decimal(str(resource.get("amount", 0))) if resource.get("amount") else Decimal(0),
        currency=resource.get("currency", ""),
        method=PaymentMethodType.WALLET,
        extra={
            "event_type": event_type,
            "resource": resource,
        },
        provider_meta=ProviderMeta(
            provider="utrust",
            raw_id=resource.get("reference", ""),
            raw_payload=webhook_data,
            fetched_at=datetime.now(UTC),
        ),
    )


def webhook_event_from_utrust(webhook_data: dict) -> WebhookEvent:
    event_type_str = webhook_data.get("event_type", "")
    event_type = WEBHOOK_EVENT_MAP.get(event_type_str, WebhookEventType.UNKNOWN)
    resource = webhook_data.get("resource", {})

    return WebhookEvent(
        event_id=resource.get("reference", ""),
        event_type=event_type,
        provider="utrust",
        provider_event_type=event_type_str,
        payload=webhook_data,
        idempotency_key=resource.get("reference", ""),
        received_at=datetime.now(UTC),
    )
