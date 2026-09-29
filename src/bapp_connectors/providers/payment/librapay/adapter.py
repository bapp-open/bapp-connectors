"""
LibraPay payment adapter — implements PaymentPort.

Form-based checkout with HMAC-SHA1. Same flow as EuPlatesc but different
signature algorithm and field naming.
"""

from __future__ import annotations

import binascii
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
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.librapay.client import (
    MAX_BACKREF_LENGTH,
    build_checkout_form,
    build_data_custom,
    generate_order_id,
    verify_ipn_hmac,
)
from bapp_connectors.providers.payment.librapay.manifest import (
    LIBRAPAY_LIVE_URL,
    LIBRAPAY_SANDBOX_URL,
    manifest,
)
from bapp_connectors.providers.payment.librapay.mappers import (
    checkout_session_from_librapay,
    payment_result_from_ipn,
    webhook_event_from_librapay,
)


class LibraPayPaymentAdapter(PaymentPort, WebhookCapability):
    """LibraPay payment adapter."""

    manifest = manifest

    # LibraPay rejects a BACKREF longer than this; hosts shorten their return URL.
    max_return_url_length = MAX_BACKREF_LENGTH

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._merchant = credentials.get("merchant", "")
        self._terminal = credentials.get("terminal", "")
        self._merchant_name = credentials.get("merchant_name", "")
        self._merchant_url = credentials.get("merchant_url", "")
        self._merchant_email = credentials.get("merchant_email", "")
        self._key_hex = credentials.get("key", "")
        self._key = b""
        if self._key_hex:
            try:
                self._key = binascii.unhexlify(self._key_hex.encode())
            except (ValueError, binascii.Error):
                pass

        self._sandbox = config.get("sandbox", False)
        self._back_url = config.get("back_url", "")
        self._form_url = LIBRAPAY_SANDBOX_URL if self._sandbox else LIBRAPAY_LIVE_URL

        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="librapay")
        self._http_client = http_client

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return bool(self._merchant and self._terminal and self._key)

    def test_connection(self) -> ConnectionTestResult:
        if not self.validate_credentials():
            return ConnectionTestResult(success=False, message="Missing merchant, terminal, or key")
        return ConnectionTestResult(
            success=True,
            message=f"LibraPay configured for terminal {self._terminal} ({'sandbox' if self._sandbox else 'live'})",
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
        """Build the auto-submitting LibraPay form.

        LibraPay's ORDER must be 6-19 digits, so a numeric one is generated and
        returned as ``session_id``; the caller's ``identifier`` goes into DESC,
        which LibraPay echoes back in the IPN (max 50 chars, shown to the payer).
        """
        currency = (currency or "RON").upper()
        if currency != "RON":
            raise ValidationError(f"LibraPay accepts only RON payments, not {currency}.")
        back_url = success_url or self._back_url or ""
        if len(back_url) > MAX_BACKREF_LENGTH:
            raise ValidationError(
                f"LibraPay return URL is {len(back_url)} characters; the limit is {MAX_BACKREF_LENGTH}."
            )
        email = (billing.email if billing else "") or client_email or ""
        name = ""
        if billing:
            name = billing.company or f"{billing.first_name} {billing.last_name}".strip()
        data_custom = build_data_custom(
            amount=float(amount),
            description=description,
            email=email,
            name=name or email,
            phone=billing.phone if billing else "",
            city=billing.city if billing else "",
            country=billing.country if billing else "",
            address=billing.address_line1 if billing else "",
            tax_id=billing.tax_id if billing else "",
        )
        form_data = build_checkout_form(
            amount=float(amount),
            currency=currency,
            order_id=generate_order_id(),
            description=identifier,
            merchant=self._merchant,
            terminal=self._terminal,
            merchant_name=self._merchant_name,
            merchant_url=self._merchant_url,
            merchant_email=self._merchant_email,
            key=self._key,
            back_url=back_url,
            data_custom=data_custom,
        )
        return checkout_session_from_librapay(form_data, self._form_url, description)

    def get_payment(self, payment_id: str) -> PaymentResult:
        raise NotImplementedError("LibraPay does not support querying payment status via API. Use IPN notifications.")

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        raise NotImplementedError("LibraPay refunds are processed via the merchant back office.")

    # ── Webhook / IPN ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        try:
            if body.startswith(b"{"):
                ipn_data = json.loads(body)
            else:
                from urllib.parse import parse_qs
                parsed = parse_qs(body.decode(), keep_blank_values=True)
                ipn_data = {k: v[0] for k, v in parsed.items()}
        except Exception:
            return False

        key = self._key
        if secret:
            try:
                key = binascii.unhexlify(secret.encode())
            except (ValueError, binascii.Error):
                key = secret.encode()

        return verify_ipn_hmac(ipn_data, key)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        try:
            if body.startswith(b"{"):
                ipn_data = json.loads(body)
            else:
                from urllib.parse import parse_qs
                parsed = parse_qs(body.decode(), keep_blank_values=True)
                ipn_data = {k: v[0] for k, v in parsed.items()}
        except Exception:
            ipn_data = {}

        return webhook_event_from_librapay(ipn_data)

    def webhook_response(self, outcome: str) -> str:
        """LibraPay resends the IPN until the body is exactly "1".

        A forged or unverifiable IPN is acknowledged too (retrying cannot fix a
        bad signature, and phclient does the same); only an error on our side
        withholds the "1" so LibraPay tries again.
        """
        return "0" if outcome == "error" else "1"

    def get_payment_from_ipn(self, ipn_data: dict) -> PaymentResult:
        """Parse an already-decoded IPN dict into a PaymentResult."""
        return payment_result_from_ipn(ipn_data)
