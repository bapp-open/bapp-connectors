"""MobilPay <-> DTO mappers."""

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


def checkout_session_from_mobilpay(
    enc_data: str, env_key: str, form_url: str, order_id: str, amount: Decimal, currency: str,
) -> CheckoutSession:
    return CheckoutSession(
        session_id=order_id,
        payment_url=form_url,
        amount=amount,
        currency=currency,
        extra={
            "form_data": {"data": enc_data, "env_key": env_key},
            "form_action": form_url,
        },
        provider_meta=ProviderMeta(
            provider="mobilpay",
            raw_id=order_id,
            raw_payload={"enc_data": enc_data, "env_key": env_key},
            fetched_at=datetime.now(UTC),
        ),
    )


def payment_result_from_mobilpay(ipn_data: dict) -> PaymentResult:
    error_code = ipn_data.get("error_code", "")
    try:
        code_int = int(error_code)
    except (ValueError, TypeError):
        code_int = -1

    status = "approved" if code_int == 0 else f"error_{error_code}"

    amount_str = ipn_data.get("amount") or ipn_data.get("processed_amount") or "0"

    return PaymentResult(
        payment_id=ipn_data.get("order_id", ""),
        status=status,
        amount=Decimal(str(amount_str)),
        currency=ipn_data.get("currency", "RON"),
        method=PaymentMethodType.CARD,
        extra={
            "error_code": error_code,
            "error_message": ipn_data.get("error_message", ""),
            "action": ipn_data.get("action", ""),
            "crc": ipn_data.get("crc", ""),
            "purchase_id": ipn_data.get("purchase_id", ""),
            "pan_masked": ipn_data.get("pan_masked", ""),
            "token_id": ipn_data.get("token_id", ""),
        },
        provider_meta=ProviderMeta(
            provider="mobilpay",
            raw_id=ipn_data.get("order_id", ""),
            raw_payload=ipn_data,
            fetched_at=datetime.now(UTC),
        ),
    )


def webhook_event_from_mobilpay(ipn_data: dict) -> WebhookEvent:
    error_code = ipn_data.get("error_code", "")
    try:
        code_int = int(error_code)
    except (ValueError, TypeError):
        code_int = -1

    event_type = WebhookEventType.ORDER_UPDATED if code_int == 0 else WebhookEventType.UNKNOWN

    return WebhookEvent(
        event_id=ipn_data.get("order_id", ""),
        event_type=event_type,
        provider="mobilpay",
        provider_event_type=f"payment.error_{error_code}",
        payload=ipn_data,
        idempotency_key=ipn_data.get("crc", ipn_data.get("order_id", "")),
        received_at=datetime.now(UTC),
    )
