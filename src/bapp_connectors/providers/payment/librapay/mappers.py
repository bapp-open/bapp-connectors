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

# TRTYPE of a refund IPN (pay_sales.php): 24 full, 25 partial.
REFUND_TRTYPES = {"24", "25"}


def checkout_session_from_librapay(form_data: dict, form_url: str, description: str = "") -> CheckoutSession:
    return CheckoutSession(
        session_id=form_data.get("ORDER", ""),
        payment_url=form_url,
        amount=Decimal(str(form_data.get("AMOUNT", 0))),
        currency=form_data.get("CURRENCY", "RON"),
        description=description or form_data.get("DESC", ""),
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
    if rc == "00" and ipn_data.get("TRTYPE") in REFUND_TRTYPES:
        status = "refunded"

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


# ACTION: 0 approved, 1 duplicate, 2 denied, 3 processing error (manual IV.4.2).
LIBRAPAY_ACTION_EVENTS: dict[str, WebhookEventType] = {
    "2": WebhookEventType.PAYMENT_FAILED,
    "3": WebhookEventType.PAYMENT_FAILED,
}


def webhook_event_from_librapay(ipn_data: dict) -> WebhookEvent:
    action = ipn_data.get("ACTION", "")
    rc = ipn_data.get("RC", "")
    order = ipn_data.get("ORDER", "")
    if not ipn_data.get("DESC"):
        # LibraPay's sync pings come without DESC; phclient ignores them too.
        event_type = WebhookEventType.UNKNOWN
    elif action == "0" and rc == "00":
        # A refund (pay_sales.php, TRTYPE 24/25) is reported the same way as the
        # sale; without this it would read as a second completed payment.
        refund = ipn_data.get("TRTYPE") in REFUND_TRTYPES
        event_type = WebhookEventType.PAYMENT_REFUNDED if refund else WebhookEventType.PAYMENT_COMPLETED
    else:
        event_type = LIBRAPAY_ACTION_EVENTS.get(action, WebhookEventType.UNKNOWN)
    return WebhookEvent(
        event_id=ipn_data.get("INT_REF") or order,
        event_type=event_type,
        provider="librapay",
        provider_event_type=f"payment.action_{action}.rc_{rc}",
        payload=ipn_data,
        # INT_REF is empty on declines; ORDER is unique per attempt, and a retry
        # after a decline needs a fresh checkout (new ORDER) anyway.
        idempotency_key=f"{order}:{action}:{rc}",
        received_at=datetime.now(UTC),
    )
