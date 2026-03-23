"""
Stripe payment adapter — implements PaymentPort + WebhookCapability.

This is the main entry point for the Stripe integration.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import WebhookCapability
from bapp_connectors.core.dto import (
    CheckoutSession,
    ConnectionTestResult,
    PaymentResult,
    Refund,
    WebhookEvent,
)
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.stripe.client import StripeApiClient
from bapp_connectors.providers.payment.stripe.errors import StripeWebhookError
from bapp_connectors.providers.payment.stripe.manifest import manifest
from bapp_connectors.providers.payment.stripe.mappers import (
    amount_to_stripe,
    checkout_session_from_stripe,
    payment_from_stripe,
    refund_from_stripe,
    webhook_event_from_stripe,
)

if TYPE_CHECKING:
    from decimal import Decimal


class StripePaymentAdapter(PaymentPort, WebhookCapability):
    """
    Stripe payment adapter.

    Implements:
    - PaymentPort: checkout sessions, payment status, refunds
    - WebhookCapability: webhook verification and parsing
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, **kwargs):
        self.credentials = credentials
        self.secret_key = credentials.get("secret_key", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=BearerAuth(token=self.secret_key),
                provider_name="stripe",
            )
        else:
            # Ensure Bearer auth is applied even when the registry provides the client
            # (CUSTOM auth strategy means the registry passes NoAuth).
            http_client.auth = BearerAuth(token=self.secret_key)

        self.client = StripeApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

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
    ) -> CheckoutSession:
        stripe_amount = amount_to_stripe(amount, currency)
        response = self.client.create_checkout_session(
            amount=stripe_amount,
            currency=currency,
            description=description,
            identifier=identifier,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=client_email,
        )
        return checkout_session_from_stripe(response)

    def get_payment(self, payment_id: str) -> PaymentResult:
        response = self.client.get_payment_intent(payment_id)
        return payment_from_stripe(response)

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        stripe_amount = None
        if amount is not None:
            # We need currency to convert; fetch the payment intent first
            pi = self.client.get_payment_intent(payment_id)
            currency = pi.get("currency") or "usd"
            stripe_amount = amount_to_stripe(amount, currency)

        response = self.client.create_refund(
            payment_intent_id=payment_id,
            amount=stripe_amount,
            reason=reason or None,
        )
        return refund_from_stripe(response)

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """
        Verify Stripe webhook signature.

        Stripe uses the format: t=timestamp,v1=signature
        The signed payload is: "{timestamp}.{body}"
        """
        sig_header = headers.get("Stripe-Signature") or headers.get("stripe-signature", "")
        if not sig_header:
            return False

        webhook_secret = secret or self.credentials.get("webhook_secret", "")
        if not webhook_secret:
            return False

        # Parse the signature header
        elements: dict[str, str] = {}
        for item in sig_header.split(","):
            key_val = item.strip().split("=", 1)
            if len(key_val) == 2:
                elements[key_val[0]] = key_val[1]

        timestamp = elements.get("t", "")
        signature = elements.get("v1", "")
        if not timestamp or not signature:
            return False

        # Check timestamp tolerance (5 minutes)
        try:
            ts = int(timestamp)
            if abs(time.time() - ts) > 300:
                return False
        except ValueError:
            return False

        # Compute expected signature
        signed_payload = f"{timestamp}.{body.decode('utf-8')}"
        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse a Stripe webhook payload into a normalized WebhookEvent."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise StripeWebhookError(f"Invalid webhook payload: {exc}") from exc

        return webhook_event_from_stripe(data)
