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

from bapp_connectors.core.capabilities import SavedPaymentCapability, SubscriptionCapability, WebhookCapability
from bapp_connectors.core.dto import (
    CheckoutSession,
    ConnectionTestResult,
    PaymentResult,
    Refund,
    SavedPaymentMethod,
    Subscription,
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
    payment_method_from_stripe,
    refund_from_stripe,
    subscription_from_stripe,
    webhook_event_from_stripe,
)

if TYPE_CHECKING:
    from decimal import Decimal


class StripePaymentAdapter(PaymentPort, WebhookCapability, SubscriptionCapability, SavedPaymentCapability):
    """
    Stripe payment adapter.

    Implements:
    - PaymentPort: checkout sessions, payment status, refunds
    - WebhookCapability: webhook verification and parsing
    - SubscriptionCapability: recurring billing via checkout
    - SavedPaymentCapability: customer management, card saving, direct charges
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
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
        # Stripe requires success_url for hosted checkout sessions
        if not success_url:
            success_url = "https://example.com/return"
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

    # ── SubscriptionCapability ──

    def create_subscription_checkout(
        self,
        price_id: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        customer_email: str | None = None,
        trial_days: int | None = None,
        metadata: dict | None = None,
    ) -> CheckoutSession:
        if not success_url:
            success_url = "https://example.com/return"
        response = self.client.create_subscription_checkout(
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            trial_days=trial_days,
            metadata=metadata,
        )
        return checkout_session_from_stripe(response)

    def get_subscription(self, subscription_id: str) -> Subscription:
        response = self.client.get_subscription(subscription_id)
        return subscription_from_stripe(response)

    def cancel_subscription(self, subscription_id: str, immediate: bool = False) -> Subscription:
        if immediate:
            response = self.client.cancel_subscription(subscription_id)
        else:
            response = self.client.update_subscription(
                subscription_id,
                cancel_at_period_end="true",
            )
        return subscription_from_stripe(response)

    def update_subscription(self, subscription_id: str, price_id: str) -> Subscription:
        # Get current subscription to find the item ID to replace
        current = self.client.get_subscription(subscription_id)
        items = current.get("items", {}).get("data", [])
        if not items:
            from bapp_connectors.core.errors import PermanentProviderError
            raise PermanentProviderError("Subscription has no items to update")

        item_id = items[0]["id"]
        response = self.client.update_subscription(
            subscription_id,
            **{
                f"items[0][id]": item_id,
                f"items[0][price]": price_id,
            },
        )
        return subscription_from_stripe(response)

    def pause_subscription(self, subscription_id: str) -> Subscription:
        response = self.client.update_subscription(
            subscription_id,
            **{"pause_collection[behavior]": "void"},
        )
        return subscription_from_stripe(response)

    def resume_subscription(self, subscription_id: str) -> Subscription:
        response = self.client.update_subscription(
            subscription_id,
            pause_collection="",
        )
        return subscription_from_stripe(response)

    # ── SavedPaymentCapability ──

    def create_customer(
        self,
        email: str,
        name: str = "",
        metadata: dict | None = None,
    ) -> str:
        response = self.client.create_customer(
            email=email, name=name, metadata=metadata,
        )
        return response["id"]

    def create_setup_checkout(
        self,
        customer_id: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> CheckoutSession:
        if not success_url:
            success_url = "https://example.com/return"
        response = self.client.create_setup_checkout(
            customer_id=customer_id,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return checkout_session_from_stripe(response)

    def list_payment_methods(self, customer_id: str) -> list[SavedPaymentMethod]:
        # Get default PM from customer for is_default flagging
        customer = self.client.get_customer(customer_id)
        default_pm = (
            customer.get("invoice_settings", {}).get("default_payment_method") or ""
        )

        response = self.client.list_payment_methods(customer_id)
        return [
            payment_method_from_stripe(pm, default_pm_id=default_pm)
            for pm in response.get("data", [])
        ]

    def delete_payment_method(self, payment_method_id: str) -> bool:
        self.client.detach_payment_method(payment_method_id)
        return True

    def charge_saved_method(
        self,
        customer_id: str,
        payment_method_id: str,
        amount: Decimal,
        currency: str,
        description: str = "",
        metadata: dict | None = None,
    ) -> PaymentResult:
        stripe_amount = amount_to_stripe(amount, currency)
        response = self.client.create_payment_intent(
            customer_id=customer_id,
            payment_method_id=payment_method_id,
            amount=stripe_amount,
            currency=currency,
            description=description,
            metadata=metadata,
        )
        return payment_from_stripe(response)

    def get_customer(self, customer_id: str) -> dict:
        return self.client.get_customer(customer_id)

    def set_default_payment_method(
        self, customer_id: str, payment_method_id: str,
    ) -> bool:
        self.client.update_customer(
            customer_id,
            **{"invoice_settings[default_payment_method]": payment_method_id},
        )
        return True

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
