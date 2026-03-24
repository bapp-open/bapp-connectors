"""LibraPay <-> DTO mappers."""

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


def checkout_session_from_librapay(form_data: dict, form_url: str) -> CheckoutSession:
    return CheckoutSession(
        session_id=form_data.get("ORDER", ""),
        payment_url=form_url,
        amount=Decimal(str(form_data.get("AMOUNT", 0))),
        currency=form_data.get("CURRENCY", "RON"),
        description=form_data.get("DESC", ""),
        extra={"form_data": form_data, "form_action": form_url},
        provider_meta=ProviderMeta(
            provider="librapay",
            raw_id=form_data.get("ORDER", ""),
            raw_payload=form_data,
            fetched_at=datetime.now(UTC),
        ),
    )


def payment_result_from_ipn(ipn_data: dict) -> PaymentResult:
    rc = ipn_data.get("RC", "")
    status = "approved" if rc == "00" else f"error_{rc}"

    return PaymentResult(
        payment_id=ipn_data.get("INT_REF", ipn_data.get("ORDER", "")),
        status=status,
        amount=Decimal(str(ipn_data.get("AMOUNT", 0))),
        currency=ipn_data.get("CURRENCY", ""),
        method=PaymentMethodType.CARD,
        extra={
            "rc": rc,
            "action": ipn_data.get("ACTION", ""),
            "message": ipn_data.get("MESSAGE", ""),
            "rrn": ipn_data.get("RRN", ""),
            "approval": ipn_data.get("APPROVAL", ""),
            "order": ipn_data.get("ORDER", ""),
            "desc": ipn_data.get("DESC", ""),
        },
        provider_meta=ProviderMeta(
            provider="librapay",
            raw_id=ipn_data.get("INT_REF", ""),
            raw_payload=ipn_data,
            fetched_at=datetime.now(UTC),
        ),
    )


def webhook_event_from_librapay(ipn_data: dict) -> WebhookEvent:
    rc = ipn_data.get("RC", "")
    event_type = WebhookEventType.ORDER_UPDATED if rc == "00" else WebhookEventType.UNKNOWN

    return WebhookEvent(
        event_id=ipn_data.get("INT_REF", ipn_data.get("ORDER", "")),
        event_type=event_type,
        provider="librapay",
        provider_event_type=f"payment.rc_{rc}",
        payload=ipn_data,
        idempotency_key=ipn_data.get("INT_REF", ""),
        received_at=datetime.now(UTC),
    )
