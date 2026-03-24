"""
EuPlatesc payment adapter — implements PaymentPort.

EuPlatesc uses a form-based checkout flow:
1. create_checkout_session() builds signed form data → consumer renders as HTML form
2. Customer submits form → redirected to EuPlatesc → pays → IPN callback
3. IPN verified via verify_webhook() → parsed via parse_webhook()

There's no REST API for querying payments — get_payment() raises NotImplementedError.
Refunds are manual (via EuPlatesc back office).
"""

from __future__ import annotations

import binascii
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
from bapp_connectors.providers.payment.euplatesc.client import (
    build_checkout_form,
    verify_ipn_hmac,
)
from bapp_connectors.providers.payment.euplatesc.manifest import manifest
from bapp_connectors.providers.payment.euplatesc.mappers import (
    checkout_session_from_euplatesc,
    payment_result_from_ipn,
    webhook_event_from_euplatesc,
)


class EuPlatescPaymentAdapter(PaymentPort, WebhookCapability):
    """
    EuPlatesc payment adapter.

    Implements:
    - PaymentPort: create_checkout_session (form-based), get_payment (limited), refund (not supported)
    - Webhook verification + parsing for IPN
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._merchant_id = credentials.get("merchant_id", "")
        self._merchant_key_hex = credentials.get("merchant_key", "")
        self._merchant_key = b""
        if self._merchant_key_hex:
            try:
                self._merchant_key = binascii.unhexlify(self._merchant_key_hex.encode())
            except (ValueError, binascii.Error):
                pass

        self._default_currency = config.get("default_currency", "RON")
        self._notify_url = config.get("notify_url", "")
        self._back_url = config.get("back_url", "")

        # EuPlatesc doesn't have a REST API, but we keep the http_client
        # for potential status check endpoints in the future
        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=NoAuth(),
                provider_name="euplatesc",
            )
        self._http_client = http_client

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return bool(self._merchant_id and self._merchant_key)

    def test_connection(self) -> ConnectionTestResult:
        if not self.validate_credentials():
            return ConnectionTestResult(success=False, message="Missing merchant_id or merchant_key")
        if not self._merchant_key:
            return ConnectionTestResult(success=False, message="Invalid merchant_key (must be hex-encoded)")
        return ConnectionTestResult(
            success=True,
            message=f"EuPlatesc configured for merchant {self._merchant_id}",
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
        """Build EuPlatesc checkout form data with HMAC signature.

        The returned CheckoutSession contains:
        - payment_url: EuPlatesc form action URL
        - extra.form_data: dict of all form fields (render as hidden inputs)
        - extra.form_action: the form POST URL
        """
        back_url = success_url or self._back_url or ""
        client_data = {}
        if client_email:
            client_data["email"] = client_email

        form_data = build_checkout_form(
            amount=float(amount),
            currency=currency or self._default_currency,
            invoice_id=identifier,
            description=description,
            merchant_id=self._merchant_id,
            merchant_key=self._merchant_key,
            back_url=back_url,
            client_data=client_data,
        )

        return checkout_session_from_euplatesc(form_data)

    def get_payment(self, payment_id: str) -> PaymentResult:
        """EuPlatesc doesn't have a REST API for querying payments.
        Payment results come exclusively via IPN notifications.
        """
        raise NotImplementedError(
            "EuPlatesc does not support querying payment status via API. "
            "Use IPN webhook notifications to receive payment results."
        )

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        """EuPlatesc refunds must be processed via the merchant back office."""
        raise NotImplementedError(
            "EuPlatesc refunds are processed manually via the merchant back office at secure.euplatesc.ro."
        )

    # ── Webhook / IPN ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify an EuPlatesc IPN HMAC-MD5 signature.

        EuPlatesc sends the signature in the POST body as fp_hash, not in a header.
        The body should be parsed as form data (application/x-www-form-urlencoded).
        """
        try:
            # Body can be form-encoded or JSON
            if body.startswith(b"{"):
                ipn_data = json.loads(body)
            else:
                # Parse form data
                from urllib.parse import parse_qs
                parsed = parse_qs(body.decode(), keep_blank_values=True)
                ipn_data = {k: v[0] for k, v in parsed.items()}
        except Exception:
            return False

        key = self._merchant_key
        if secret:
            try:
                key = binascii.unhexlify(secret.encode())
            except (ValueError, binascii.Error):
                key = secret.encode()

        return verify_ipn_hmac(ipn_data, key)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse an EuPlatesc IPN POST into a WebhookEvent."""
        try:
            if body.startswith(b"{"):
                ipn_data = json.loads(body)
            else:
                from urllib.parse import parse_qs
                parsed = parse_qs(body.decode(), keep_blank_values=True)
                ipn_data = {k: v[0] for k, v in parsed.items()}
        except Exception:
            ipn_data = {}

        return webhook_event_from_euplatesc(ipn_data)

    def get_payment_from_ipn(self, ipn_data: dict) -> PaymentResult:
        """Parse an already-decoded IPN dict into a PaymentResult.

        Convenience method for consumers that have already parsed the IPN.
        """
        return payment_result_from_ipn(ipn_data)
