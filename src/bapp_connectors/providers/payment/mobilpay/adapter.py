"""
MobilPay payment adapter — implements PaymentPort.

RSA+ARC4 encrypted XML for payment forms and IPN processing.
Uses pycryptodome and pyopenssl for cryptographic operations.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import unquote

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
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.mobilpay.client import (
    build_order_xml,
    decrypt_xml,
    encrypt_xml,
    parse_ipn_xml,
)
from bapp_connectors.providers.payment.mobilpay.manifest import (
    MOBILPAY_LIVE_URL,
    MOBILPAY_SANDBOX_URL,
    manifest,
)
from bapp_connectors.providers.payment.mobilpay.mappers import (
    checkout_session_from_mobilpay,
    payment_result_from_mobilpay,
    webhook_event_from_mobilpay,
)


class MobilPayPaymentAdapter(PaymentPort, WebhookCapability):
    """MobilPay (Netopia legacy) payment adapter."""

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._client_key = credentials.get("client_key", "")
        self._public_cert = credentials.get("public_cert", "")
        self._private_key = credentials.get("private_key", "")
        self._sandbox = config.get("sandbox", False)

        self._form_url = MOBILPAY_SANDBOX_URL if self._sandbox else MOBILPAY_LIVE_URL

        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="mobilpay")
        self._http_client = http_client

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return bool(self._client_key and self._public_cert and self._private_key)

    def test_connection(self) -> ConnectionTestResult:
        if not self.validate_credentials():
            return ConnectionTestResult(success=False, message="Missing client_key, public_cert, or private_key")
        # Verify the cert/key are valid by attempting to load them
        try:
            from bapp_connectors.providers.payment.mobilpay.client import _get_rsa_private_key, _get_rsa_public_key
            _get_rsa_public_key(self._public_cert)
            _get_rsa_private_key(self._private_key)
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Invalid certificate or key: {e}")
        return ConnectionTestResult(
            success=True,
            message=f"MobilPay configured for {self._client_key} ({'sandbox' if self._sandbox else 'live'})",
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
        xml_bytes = build_order_xml(
            client_key=self._client_key,
            order_id=identifier,
            amount=amount,
            currency=currency or "RON",
            description=description,
            confirm_url=success_url or "",
            return_url=success_url or "",
            client_email=_email,
        )

        enc_data, env_key = encrypt_xml(xml_bytes, self._public_cert)

        return checkout_session_from_mobilpay(
            enc_data=enc_data,
            env_key=env_key,
            form_url=self._form_url,
            order_id=identifier,
            amount=amount,
            currency=currency or "RON",
        )

    def get_payment(self, payment_id: str) -> PaymentResult:
        raise NotImplementedError("MobilPay does not support querying payment status via API. Use IPN notifications.")

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        raise NotImplementedError("MobilPay refunds are processed via the Netopia merchant dashboard.")

    # ── Webhook / IPN ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify MobilPay IPN by attempting to decrypt the POST data."""
        try:
            post_data = self._parse_post_body(body)
            enc_data = post_data.get("data", "")
            env_key = post_data.get("env_key", "")
            if not enc_data or not env_key:
                return False

            private_key = secret or self._private_key
            xml_bytes = decrypt_xml(unquote(enc_data), unquote(env_key), private_key)
            ipn_data = parse_ipn_xml(xml_bytes)
            return bool(ipn_data.get("order_id"))
        except Exception:
            return False

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Decrypt and parse MobilPay IPN."""
        try:
            post_data = self._parse_post_body(body)
            enc_data = post_data.get("data", "")
            env_key = post_data.get("env_key", "")
            if not enc_data or not env_key:
                raise WebhookVerificationError("Missing 'data' or 'env_key' in POST body")

            xml_bytes = decrypt_xml(unquote(enc_data), unquote(env_key), self._private_key)
            ipn_data = parse_ipn_xml(xml_bytes)
        except WebhookVerificationError:
            raise
        except Exception as exc:
            raise WebhookVerificationError(f"Failed to decrypt/parse IPN: {exc}") from exc

        return webhook_event_from_mobilpay(ipn_data)

    def get_payment_from_ipn(self, ipn_data: dict) -> PaymentResult:
        """Parse already-decoded IPN data into a PaymentResult."""
        return payment_result_from_mobilpay(ipn_data)

    def decrypt_ipn(self, enc_data: str, env_key: str) -> dict:
        """Decrypt raw IPN POST fields and return parsed data dict."""
        xml_bytes = decrypt_xml(unquote(enc_data), unquote(env_key), self._private_key)
        return parse_ipn_xml(xml_bytes)

    @staticmethod
    def _parse_post_body(body: bytes) -> dict:
        """Parse URL-encoded or JSON POST body."""
        if body.startswith(b"{"):
            import json
            return json.loads(body)
        from urllib.parse import parse_qs
        parsed = parse_qs(body.decode(), keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}
