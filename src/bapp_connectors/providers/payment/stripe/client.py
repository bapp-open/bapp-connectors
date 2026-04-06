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

    def list_payment_intents(
        self,
        *,
        limit: int = 25,
        starting_after: str | None = None,
        created_gte: int | None = None,
        created_lte: int | None = None,
    ) -> dict:
        """List payment intents with optional filters."""
        params: dict[str, Any] = {"limit": str(limit)}
        if starting_after:
            params["starting_after"] = starting_after
        if created_gte is not None:
            params["created[gte]"] = str(created_gte)
        if created_lte is not None:
            params["created[lte]"] = str(created_lte)
        return self._call("GET", "payment_intents", params=params)

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

    # ── Subscriptions ──

    def create_subscription_checkout(
        self,
        *,
        price_id: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        customer_email: str | None = None,
        trial_days: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Create a checkout session in subscription mode."""
        data: dict[str, Any] = {
            "mode": "subscription",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
        }
        if success_url:
            data["success_url"] = success_url
        if cancel_url:
            data["cancel_url"] = cancel_url
        if customer_email:
            data["customer_email"] = customer_email
        if trial_days is not None:
            data["subscription_data[trial_period_days]"] = str(trial_days)
        if metadata:
            for key, value in metadata.items():
                data[f"subscription_data[metadata][{key}]"] = value

        return self._call("POST", "checkout/sessions", data=data)

    def get_subscription(self, subscription_id: str) -> dict:
        """Retrieve a subscription by ID."""
        return self._call("GET", f"subscriptions/{subscription_id}")

    def cancel_subscription(self, subscription_id: str) -> dict:
        """Cancel a subscription immediately."""
        return self._call("DELETE", f"subscriptions/{subscription_id}")

    def update_subscription(self, subscription_id: str, **data: Any) -> dict:
        """Update a subscription."""
        return self._call("POST", f"subscriptions/{subscription_id}", data=data)

    def create_price(
        self,
        *,
        amount: int,
        currency: str,
        interval: str,
        interval_count: int = 1,
        product_name: str = "",
    ) -> dict:
        """Create a recurring price (used in tests and dynamic pricing)."""
        data: dict[str, Any] = {
            "unit_amount": str(amount),
            "currency": currency.lower(),
            "recurring[interval]": interval,
            "recurring[interval_count]": str(interval_count),
            "product_data[name]": product_name or f"{currency.upper()} {interval}ly plan",
        }
        return self._call("POST", "prices", data=data)

    # ── Customers ──

    def create_customer(
        self,
        *,
        email: str,
        name: str = "",
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Create a Stripe customer."""
        data: dict[str, Any] = {"email": email}
        if name:
            data["name"] = name
        if metadata:
            for key, value in metadata.items():
                data[f"metadata[{key}]"] = value
        return self._call("POST", "customers", data=data)

    def get_customer(self, customer_id: str) -> dict:
        """Retrieve a Stripe customer by ID."""
        return self._call("GET", f"customers/{customer_id}")

    def update_customer(self, customer_id: str, **data: Any) -> dict:
        """Update a Stripe customer."""
        return self._call("POST", f"customers/{customer_id}", data=data)

    # ── Setup (save card) ──

    def create_setup_checkout(
        self,
        *,
        customer_id: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        currency: str = "usd",
    ) -> dict:
        """Create a checkout session in setup mode (collect card without charging)."""
        data: dict[str, Any] = {
            "mode": "setup",
            "customer": customer_id,
            "currency": currency.lower(),
        }
        if success_url:
            data["success_url"] = success_url
        if cancel_url:
            data["cancel_url"] = cancel_url
        return self._call("POST", "checkout/sessions", data=data)

    # ── Payment Methods ──

    def list_payment_methods(self, customer_id: str, pm_type: str = "card") -> dict:
        """List payment methods attached to a customer."""
        return self._call(
            "GET", "payment_methods",
            params={"customer": customer_id, "type": pm_type},
        )

    def detach_payment_method(self, payment_method_id: str) -> dict:
        """Detach a payment method from its customer."""
        return self._call("POST", f"payment_methods/{payment_method_id}/detach")

    # ── Payouts ──

    def list_payouts(
        self,
        *,
        limit: int = 25,
        starting_after: str | None = None,
        created_gte: int | None = None,
        created_lte: int | None = None,
    ) -> dict:
        """List payouts (bank transfers from Stripe to seller)."""
        params: dict[str, Any] = {"limit": str(limit)}
        if starting_after:
            params["starting_after"] = starting_after
        if created_gte is not None:
            params["created[gte]"] = str(created_gte)
        if created_lte is not None:
            params["created[lte]"] = str(created_lte)
        return self._call("GET", "payouts", params=params)

    def get_payout(self, payout_id: str) -> dict:
        """Retrieve a single payout."""
        return self._call("GET", f"payouts/{payout_id}")

    # ── Balance Transactions ──

    def list_balance_transactions(
        self,
        *,
        payout: str | None = None,
        limit: int = 100,
        starting_after: str | None = None,
        created_gte: int | None = None,
        created_lte: int | None = None,
        expand: list[str] | None = None,
    ) -> dict:
        """List balance transactions, optionally filtered by payout.

        Args:
            payout: Filter by payout ID to get all transactions in a specific payout.
            expand: Stripe expand fields (e.g. ["data.source"] to include charge details).
        """
        params: dict[str, Any] = {"limit": str(limit)}
        if payout:
            params["payout"] = payout
        if starting_after:
            params["starting_after"] = starting_after
        if created_gte is not None:
            params["created[gte]"] = str(created_gte)
        if created_lte is not None:
            params["created[lte]"] = str(created_lte)
        if expand:
            for i, field in enumerate(expand):
                params[f"expand[{i}]"] = field
        return self._call("GET", "balance_transactions", params=params)

    def get_charge(self, charge_id: str, expand: list[str] | None = None) -> dict:
        """Retrieve a charge with optional expansion (e.g. customer, balance_transaction)."""
        params: dict[str, Any] = {}
        if expand:
            for i, field in enumerate(expand):
                params[f"expand[{i}]"] = field
        return self._call("GET", f"charges/{charge_id}", params=params)

    # ── Direct Charge (off-session) ──

    def create_payment_intent(
        self,
        *,
        customer_id: str,
        payment_method_id: str,
        amount: int,
        currency: str,
        description: str = "",
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Create and confirm a PaymentIntent using a saved payment method."""
        data: dict[str, Any] = {
            "customer": customer_id,
            "payment_method": payment_method_id,
            "amount": str(amount),
            "currency": currency.lower(),
            "confirm": "true",
            "off_session": "true",
        }
        if description:
            data["description"] = description
        if metadata:
            for key, value in metadata.items():
                data[f"metadata[{key}]"] = value
        return self._call("POST", "payment_intents", data=data)
