"""PayPal <-> DTO mappers."""

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
