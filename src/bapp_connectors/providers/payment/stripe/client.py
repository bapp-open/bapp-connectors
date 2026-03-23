"""
Stripe API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
Stripe accepts form-encoded POST bodies by default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class StripeApiClient:
    """
    Low-level Stripe API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def _call(self, method: str, path: str, **kwargs: Any) -> dict | list | str:
        return self.http.call(method, path, **kwargs)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by fetching the account balance."""
        try:
            self._call("GET", "balance")
            return True
        except Exception:
            return False

    # ── Checkout Sessions ──

    def create_checkout_session(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        identifier: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        customer_email: str | None = None,
    ) -> dict:
        """Create a Stripe checkout session. Amount is in smallest currency unit."""
        data: dict[str, Any] = {
            "mode": "payment",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][product_data][name]": description,
            "line_items[0][price_data][unit_amount]": str(amount),
            "line_items[0][quantity]": "1",
            "metadata[identifier]": identifier,
        }
        if success_url:
            data["success_url"] = success_url
        if cancel_url:
            data["cancel_url"] = cancel_url
        if customer_email:
            data["customer_email"] = customer_email

        return self._call("POST", "checkout/sessions", data=data)

    # ── Payment Intents ──

    def get_payment_intent(self, payment_intent_id: str) -> dict:
        """Retrieve a payment intent by ID."""
        return self._call("GET", f"payment_intents/{payment_intent_id}")

    # ── Refunds ──

    def create_refund(
        self,
        payment_intent_id: str,
        amount: int | None = None,
        reason: str | None = None,
    ) -> dict:
        """Create a refund for a payment intent. Amount is in smallest currency unit."""
        data: dict[str, Any] = {
            "payment_intent": payment_intent_id,
        }
        if amount is not None:
            data["amount"] = str(amount)
        if reason:
            data["reason"] = reason

        return self._call("POST", "refunds", data=data)
