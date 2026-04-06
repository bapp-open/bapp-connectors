"""
PayPal payment adapter — implements PaymentPort.

REST API with OAuth2 client credentials. Supports order creation,
payment status query, refunds, and webhook parsing.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
from bapp_connectors.core.dto import (
    CheckoutSession,
    ConnectionTestResult,
    FinancialTransaction,
    PaginatedResult,
    PaymentResult,
    Refund,
    WebhookEvent,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto import BillingDetails
from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.paypal.client import PayPalApiClient
from bapp_connectors.providers.payment.paypal.manifest import (
    PAYPAL_LIVE_URL,
    PAYPAL_SANDBOX_URL,
    manifest,
)
from bapp_connectors.providers.payment.paypal.mappers import (
    checkout_session_from_paypal,
    payment_result_from_paypal,
    refund_from_paypal,
    transactions_from_paypal,
    webhook_event_from_paypal,
)


class PayPalPaymentAdapter(PaymentPort, WebhookCapability, FinancialCapability):
    """PayPal payment adapter."""

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._client_id = credentials.get("client_id", "")
        self._app_secret = credentials.get("app_secret", "")
        self._sandbox = config.get("sandbox", False)

        base_url = PAYPAL_SANDBOX_URL if self._sandbox else PAYPAL_LIVE_URL

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=NoAuth(),  # Auth handled by client via OAuth2
                provider_name="paypal",
            )

        self._client = PayPalApiClient(
            http_client=http_client,
            client_id=self._client_id,
            app_secret=self._app_secret,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return bool(self._client_id and self._app_secret)

    def test_connection(self) -> ConnectionTestResult:
        if not self.validate_credentials():
            return ConnectionTestResult(success=False, message="Missing client_id or app_secret")
        try:
            success = self._client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="PayPal connection successful" if success else "Authentication failed",
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
        response = self._client.create_order(
            amount=float(amount),
            currency=currency or "EUR",
            description=description,
            order_id=identifier,
            return_url=success_url or "",
            cancel_url=cancel_url or "",
        )
        return checkout_session_from_paypal(response)

    def get_payment(self, payment_id: str) -> PaymentResult:
        response = self._client.get_order(payment_id)
        return payment_result_from_paypal(response)

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        response = self._client.create_refund(
            capture_id=payment_id,
            amount=float(amount) if amount else None,
        )
        return refund_from_paypal(response, payment_id)

    # ── FinancialCapability ──

    def get_financial_transactions(
        self,
        start_date: datetime,
        end_date: datetime,
        transaction_type: str | None = None,
        cursor: str | None = None,
    ) -> PaginatedResult[FinancialTransaction]:
        """Fetch transactions from PayPal reporting API.

        Args:
            start_date: Start of date range (max 31-day span).
            end_date: End of date range.
            transaction_type: PayPal transaction event code filter (e.g. "T0006" for payouts).
            cursor: Page number as string (1-based).
        """
        page = int(cursor) if cursor else 1
        response = self._client.list_transactions(
            start_date=start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_date=end_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            transaction_type=transaction_type,
            page=page,
        )
        return transactions_from_paypal(response)

    # ── Webhook ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return False

        event_type = data.get("event_type", "")
        return event_type in (
            "CHECKOUT.ORDER.APPROVED",
            "PAYMENT.CAPTURE.COMPLETED",
            "PAYMENT.CAPTURE.DENIED",
        )

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise WebhookVerificationError(f"Invalid JSON payload: {exc}") from exc

        return webhook_event_from_paypal(data)
