"""
Netopia payment adapter — implements PaymentPort.

This is the main entry point for the Netopia integration.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import WebhookCapability
from bapp_connectors.core.dto import (
    CheckoutSession,
    ConnectionTestResult,
    PaymentResult,
    Refund,
    WebhookEvent,
)
from bapp_connectors.core.http import MultiHeaderAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.netopia.client import NetopiaApiClient
from bapp_connectors.providers.payment.netopia.manifest import (
    NETOPIA_LIVE_URL,
    NETOPIA_SANDBOX_URL,
    manifest,
)
from bapp_connectors.providers.payment.netopia.mappers import (
    checkout_session_from_netopia,
    payment_from_netopia,
    webhook_event_from_netopia,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from bapp_connectors.core.dto import BillingDetails


class NetopiaPaymentAdapter(PaymentPort, WebhookCapability):
    """
    Netopia payment adapter.

    Implements:
    - PaymentPort: checkout sessions, payment status, refunds
    - WebhookCapability: IPN notification parsing
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self.api_key = credentials.get("api_key", "")
        self.pos_signature = credentials.get("pos_signature", "")
        self.sandbox = str(credentials.get("sandbox", "true")).lower() in ("true", "1", "yes")

        base_url = NETOPIA_SANDBOX_URL if self.sandbox else NETOPIA_LIVE_URL

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=MultiHeaderAuth(
                    {
                        "Authorization": self.api_key,
                    }
                ),
                provider_name="netopia",
            )
        else:
            # Ensure custom auth is applied even when the registry provides the client
            # (CUSTOM auth strategy means the registry passes NoAuth).
            http_client.auth = MultiHeaderAuth(
                {
                    "Authorization": self.api_key,
                }
            )
            # Override base_url for sandbox/live switching
            http_client.base_url = base_url.rstrip("/") + "/"

        self.client = NetopiaApiClient(
            http_client=http_client,
            api_key=self.api_key,
            pos_signature=self.pos_signature,
            sandbox=self.sandbox,
            notify_url=config.get("notify_url", ""),
            redirect_url=config.get("redirect_url", ""),
        )

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
        billing: BillingDetails | None = None,
    ) -> CheckoutSession:
        _email = (billing.email if billing else None) or client_email or ""
        _phone = billing.phone if billing else ""
        response = self.client.start_payment(
            amount=float(amount),
            currency=currency,
            description=description,
            order_id=identifier,
            client_email=_email,
            client_phone=_phone,
            cancel_url=cancel_url or "",
            success_url=success_url or "",
        )
        return checkout_session_from_netopia(response, amount, currency, description)

    def get_payment(self, payment_id: str) -> PaymentResult:
        response = self.client.get_status(ntp_id=payment_id)
        return payment_from_netopia(response)

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        # Netopia does not expose a direct refund API through their standard flow.
        # Refunds are typically processed through the Netopia admin panel or via
        # the credit IPN callback. We raise UnsupportedFeatureError for programmatic refunds.
        from bapp_connectors.core.errors import UnsupportedFeatureError

        raise UnsupportedFeatureError(
            "Netopia does not support programmatic refunds via API. Use the Netopia admin panel to process refunds."
        )

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify a Netopia IPN notification.

        Netopia IPN sends JSON with payment status. The verification is done
        by checking that the payload is valid JSON and contains expected fields.
        Netopia does not use HMAC signatures on IPN — instead, the notifyUrl
        must be a server-side endpoint that Netopia calls directly.
        """
        try:
            data = json.loads(body)
            # Basic structure check
            return "payment" in data or "order" in data or "status" in data
        except (json.JSONDecodeError, ValueError):
            return False

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse a Netopia IPN JSON payload into a WebhookEvent."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            data = {}
        return webhook_event_from_netopia(data)
