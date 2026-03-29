"""
Cardinity payment adapter — implements PaymentPort.

Form-based checkout with HMAC-SHA256 signature. Customer is redirected to
Cardinity hosted payment page, then POST-ed back with payment status.
"""

from __future__ import annotations

import json
from decimal import Decimal

from bapp_connectors.core.capabilities import WebhookCapability
from bapp_connectors.core.dto import (
    CheckoutSession,
    ConnectionTestResult,
    PaymentResult,
    Refund,
    WebhookEvent,
)
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.cardinity.client import build_checkout_form
from bapp_connectors.providers.payment.cardinity.manifest import (
    CARDINITY_CHECKOUT_URL,
    manifest,
)
from bapp_connectors.providers.payment.cardinity.mappers import (
    checkout_session_from_cardinity,
    payment_result_from_cardinity,
    webhook_event_from_cardinity,
)


class CardinityPaymentAdapter(PaymentPort, WebhookCapability):
    """Cardinity payment adapter."""

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._project_key = credentials.get("project_key", "")
        self._project_secret = credentials.get("project_secret", "")
        self._default_country = config.get("default_country", "LT")

        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="cardinity")
        self._http_client = http_client

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return bool(self._project_key and self._project_secret)

    def test_connection(self) -> ConnectionTestResult:
        if not self.validate_credentials():
            return ConnectionTestResult(success=False, message="Missing project_key or project_secret")
        return ConnectionTestResult(
            success=True,
            message=f"Cardinity configured for project {self._project_key}",
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
    ) -> CheckoutSession:
        return_url = success_url or ""
        cxl_url = cancel_url or ""

        form_data = build_checkout_form(
            amount=float(amount),
            currency=currency or "EUR",
            order_id=identifier,
            description=description,
            project_key=self._project_key,
            project_secret=self._project_secret,
            return_url=return_url,
            cancel_url=cxl_url,
            country=self._default_country,
        )

        return checkout_session_from_cardinity(form_data, CARDINITY_CHECKOUT_URL)

    def get_payment(self, payment_id: str) -> PaymentResult:
        raise NotImplementedError("Cardinity does not support querying payment status via API. Use redirect POST data.")

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        raise NotImplementedError("Cardinity refunds are processed via the merchant dashboard.")

    # ── Webhook / IPN ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        try:
            if body.startswith(b"{"):
                post_data = json.loads(body)
            else:
                from urllib.parse import parse_qs
                parsed = parse_qs(body.decode(), keep_blank_values=True)
                post_data = {k: v[0] for k, v in parsed.items()}
        except Exception:
            return False

        status = post_data.get("status", "")
        return status in ("approved", "pending", "declined")

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        try:
            if body.startswith(b"{"):
                post_data = json.loads(body)
            else:
                from urllib.parse import parse_qs
                parsed = parse_qs(body.decode(), keep_blank_values=True)
                post_data = {k: v[0] for k, v in parsed.items()}
        except Exception:
            post_data = {}

        return webhook_event_from_cardinity(post_data)

    def get_payment_from_post(self, post_data: dict) -> PaymentResult:
        """Parse POST return data into a PaymentResult."""
        return payment_result_from_cardinity(post_data)
