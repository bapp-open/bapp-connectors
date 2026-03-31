"""
Utrust payment adapter — implements PaymentPort.

REST API for order creation, HMAC-SHA256 webhook verification.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import WebhookCapability
from bapp_connectors.core.dto import (
    CheckoutSession,
    ConnectionTestResult,
    PaymentResult,
    Refund,
    WebhookEvent,
)

if TYPE_CHECKING:
    from bapp_connectors.core.dto import BillingDetails
from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.utrust.client import UtrustApiClient, verify_hmac
from bapp_connectors.providers.payment.utrust.manifest import (
    UTRUST_LIVE_URL,
    UTRUST_SANDBOX_URL,
    manifest,
)
from bapp_connectors.providers.payment.utrust.mappers import (
    checkout_session_from_utrust,
    payment_result_from_webhook,
    webhook_event_from_utrust,
)


class UtrustPaymentAdapter(PaymentPort, WebhookCapability):
    """Utrust payment adapter."""

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._api_key = credentials.get("api_key", "")
        self._webhook_secret = credentials.get("webhook_secret", "")
        self._sandbox = config.get("sandbox", False)

        base_url = UTRUST_SANDBOX_URL if self._sandbox else UTRUST_LIVE_URL

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BearerAuth(token=self._api_key),
                provider_name="utrust",
            )
        else:
            http_client.auth = BearerAuth(token=self._api_key)

        self._client = UtrustApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return bool(self._api_key and self._webhook_secret)

    def test_connection(self) -> ConnectionTestResult:
        if not self.validate_credentials():
            return ConnectionTestResult(success=False, message="Missing api_key or webhook_secret")
        return ConnectionTestResult(
            success=True,
            message=f"Utrust configured ({'sandbox' if self._sandbox else 'live'})",
        )

    # ── PaymentPort ──

    def create_checkout_session(
        self,
        amount: Decimal,
        currency: str,
        description: str,
        identifier: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        client_email: str | None = None,
        billing: BillingDetails | None = None,
    ) -> CheckoutSession:
        _email = (billing.email if billing else None) or client_email or ""
        _first = billing.first_name if billing else ""
        _last = billing.last_name if billing else ""
        _country = billing.country if billing else ""
        response = self._client.create_order(
            reference=identifier,
            amount=float(amount),
            currency=currency or "EUR",
            description=description,
            return_url=success_url or "",
            cancel_url=cancel_url or "",
            callback_url=success_url or "",
            customer_email=_email,
            customer_first_name=_first,
            customer_last_name=_last,
            customer_country=_country,
        )
        return checkout_session_from_utrust(response, identifier, amount, currency)

    def get_payment(self, payment_id: str) -> PaymentResult:
        raise NotImplementedError("Utrust does not support querying payment status via API. Use webhooks.")

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        raise NotImplementedError("Utrust refunds are processed via the merchant dashboard.")

    # ── Webhook / IPN ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return False

        webhook_secret = secret or self._webhook_secret
        return verify_hmac(data, webhook_secret)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise WebhookVerificationError(f"Invalid JSON payload: {exc}") from exc

        return webhook_event_from_utrust(data)

    def get_payment_from_webhook(self, webhook_data: dict) -> PaymentResult:
        """Parse a webhook payload into a PaymentResult."""
        return payment_result_from_webhook(webhook_data)
