"""
Stripe payment integration tests — runs against Stripe's test-mode API.

Requires:
    STRIPE_SECRET_KEY=sk_test_... uv run --extra dev pytest tests/payment/stripe/test_integration.py -v -m integration

Optional env vars:
    STRIPE_WEBHOOK_SECRET=whsec_...  — for webhook signature tests

Tests marked with skip_unless_stripe_cli require the Stripe CLI (``stripe``)
to be installed. These use ``stripe trigger`` to create completed payments
so we can test get_payment (completed) and refund end-to-end.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import time
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import SavedPaymentCapability, SubscriptionCapability
from bapp_connectors.core.dto import (
    CardBrand,
    CheckoutSession,
    ConnectionTestResult,
    PaymentResult,
    Refund,
    SavedPaymentMethod,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
    WebhookEventType,
)
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.providers.payment.stripe.adapter import StripePaymentAdapter

from tests.payment.conftest import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    skip_unless_stripe,
    skip_unless_stripe_cli,
)

pytestmark = [pytest.mark.integration, skip_unless_stripe]


@pytest.fixture
def adapter():
    return StripePaymentAdapter(
        credentials={
            "secret_key": STRIPE_SECRET_KEY,
            "webhook_secret": STRIPE_WEBHOOK_SECRET,
        },
    )


# ── Contract tests ──


class TestStripeContract:
    """Run the full payment contract suite against Stripe test mode."""

    from tests.payment.contract import PaymentContractTests

    for _name, _method in vars(PaymentContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Connection tests ──


class TestStripeConnection:

    def test_invalid_key_fails_connection(self):
        bad = StripePaymentAdapter(credentials={"secret_key": "sk_test_invalid"})
        result = bad.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is False

    def test_empty_credentials_fails_validation(self):
        bad = StripePaymentAdapter(credentials={})
        assert bad.validate_credentials() is False


# ── Checkout session tests ──


class TestStripeCheckoutSession:

    def test_create_session_usd(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("25.00"),
            currency="USD",
            description="Test Item",
            identifier="ORDER-001",
            success_url="https://example.com/success",
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id.startswith("cs_test_")
        assert "checkout.stripe.com" in session.payment_url
        assert session.amount == Decimal("25.00")
        assert session.currency == "USD"

    def test_create_session_eur(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("10.50"),
            currency="EUR",
            description="EUR Test",
            identifier="ORDER-002",
            success_url="https://example.com/success",
        )
        assert session.amount == Decimal("10.50")
        assert session.currency == "EUR"

    def test_create_session_zero_decimal_currency(self, adapter):
        """JPY is a zero-decimal currency — amount should not be multiplied by 100."""
        session = adapter.create_checkout_session(
            amount=Decimal("1000"),
            currency="JPY",
            description="JPY Test",
            identifier="ORDER-003",
            success_url="https://example.com/success",
        )
        assert session.amount == Decimal("1000")
        assert session.currency == "JPY"

    def test_create_session_with_cancel_url(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("15.00"),
            currency="USD",
            description="Cancel URL Test",
            identifier="ORDER-004",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id

    def test_create_session_has_expiry(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("5.00"),
            currency="USD",
            description="Expiry Test",
            identifier="ORDER-005",
            success_url="https://example.com/success",
        )
        assert session.expires_at is not None

    def test_create_session_has_payment_intent(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("20.00"),
            currency="USD",
            description="PI Test",
            identifier="ORDER-006",
            success_url="https://example.com/success",
        )
        pi = session.extra.get("payment_intent")
        assert pi is not None
        assert pi.startswith("pi_")


# ── Get payment tests ──


class TestStripeGetPayment:

    def test_get_payment_from_checkout_session(self, adapter):
        """Payment intent from an uncompleted checkout should be pending."""
        session = adapter.create_checkout_session(
            amount=Decimal("30.00"),
            currency="USD",
            description="Get Payment Test",
            identifier="ORDER-007",
            success_url="https://example.com/success",
        )
        pi_id = session.extra["payment_intent"]
        result = adapter.get_payment(pi_id)

        assert isinstance(result, PaymentResult)
        assert result.payment_id == pi_id
        assert result.status == "pending"
        assert result.amount == Decimal("30.00")
        assert result.currency == "USD"

    def test_get_nonexistent_payment_raises(self, adapter):
        with pytest.raises(Exception):
            adapter.get_payment("pi_nonexistent_12345")


# ── Refund tests ──


class TestStripeRefund:

    def test_refund_uncompleted_payment_raises(self, adapter):
        """Cannot refund a payment that hasn't been completed."""
        session = adapter.create_checkout_session(
            amount=Decimal("40.00"),
            currency="USD",
            description="Refund Test",
            identifier="ORDER-008",
            success_url="https://example.com/success",
        )
        pi_id = session.extra["payment_intent"]
        with pytest.raises(PermanentProviderError):
            adapter.refund(pi_id)

    def test_refund_nonexistent_payment_raises(self, adapter):
        with pytest.raises(Exception):
            adapter.refund("pi_nonexistent_12345")


# ── Error handling tests ──


class TestStripeErrors:

    def test_invalid_amount_raises(self, adapter):
        """Stripe rejects amounts below the minimum (e.g. 0)."""
        with pytest.raises(Exception):
            adapter.create_checkout_session(
                amount=Decimal("0"),
                currency="USD",
                description="Zero Amount",
                identifier="ORDER-009",
                success_url="https://example.com/success",
            )


# ── Webhook verification tests ──


class TestStripeWebhook:
    """Webhook signature verification and event parsing.

    Uses synthetic payloads with computed HMAC signatures — no network needed,
    but tested against a live-configured adapter instance.
    """

    WEBHOOK_SECRET = STRIPE_WEBHOOK_SECRET or "whsec_test_secret"

    def _make_signed_payload(self, body: bytes, secret: str) -> dict:
        """Build a valid Stripe-Signature header for the given body."""
        timestamp = str(int(time.time()))
        signed = f"{timestamp}.{body.decode('utf-8')}"
        sig = hmac.new(
            secret.encode("utf-8"),
            signed.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"Stripe-Signature": f"t={timestamp},v1={sig}"}

    def test_verify_valid_signature(self, adapter):
        body = b'{"id": "evt_test", "type": "charge.succeeded"}'
        headers = self._make_signed_payload(body, self.WEBHOOK_SECRET)
        assert adapter.verify_webhook(headers, body, secret=self.WEBHOOK_SECRET) is True

    def test_verify_invalid_signature(self, adapter):
        body = b'{"id": "evt_test", "type": "charge.succeeded"}'
        headers = {"Stripe-Signature": "t=1234567890,v1=invalidsignature"}
        assert adapter.verify_webhook(headers, body, secret=self.WEBHOOK_SECRET) is False

    def test_verify_missing_signature_header(self, adapter):
        body = b'{"id": "evt_test"}'
        assert adapter.verify_webhook({}, body, secret=self.WEBHOOK_SECRET) is False

    def test_verify_expired_timestamp(self, adapter):
        """Signatures older than 5 minutes should be rejected."""
        body = b'{"id": "evt_test"}'
        old_ts = str(int(time.time()) - 600)
        signed = f"{old_ts}.{body.decode('utf-8')}"
        sig = hmac.new(
            self.WEBHOOK_SECRET.encode("utf-8"),
            signed.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {"Stripe-Signature": f"t={old_ts},v1={sig}"}
        assert adapter.verify_webhook(headers, body, secret=self.WEBHOOK_SECRET) is False

    def test_parse_checkout_completed(self, adapter):
        payload = {
            "id": "evt_test_123",
            "type": "checkout.session.completed",
            "api_version": "2023-10-16",
            "livemode": False,
            "data": {
                "object": {
                    "id": "cs_test_abc",
                    "payment_intent": "pi_test_abc",
                    "amount_total": 2500,
                    "currency": "usd",
                }
            },
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert isinstance(event, WebhookEvent)
        assert event.event_type == WebhookEventType.PAYMENT_COMPLETED
        assert event.provider == "stripe"
        assert event.provider_event_type == "checkout.session.completed"
        assert event.payload["id"] == "cs_test_abc"

    def test_parse_payment_failed(self, adapter):
        payload = {
            "id": "evt_test_456",
            "type": "payment_intent.payment_failed",
            "data": {"object": {"id": "pi_test_fail"}},
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.event_type == WebhookEventType.PAYMENT_FAILED

    def test_parse_charge_refunded(self, adapter):
        payload = {
            "id": "evt_test_789",
            "type": "charge.refunded",
            "data": {"object": {"id": "ch_test_refund"}},
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.event_type == WebhookEventType.PAYMENT_REFUNDED

    def test_parse_subscription_created(self, adapter):
        payload = {
            "id": "evt_test_sub_created",
            "type": "customer.subscription.created",
            "data": {"object": {"id": "sub_test_123", "status": "active"}},
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.event_type == WebhookEventType.SUBSCRIPTION_CREATED
        assert event.payload["id"] == "sub_test_123"

    def test_parse_subscription_updated(self, adapter):
        payload = {
            "id": "evt_test_sub_updated",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_test_123", "status": "past_due"}},
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.event_type == WebhookEventType.SUBSCRIPTION_UPDATED

    def test_parse_subscription_deleted(self, adapter):
        payload = {
            "id": "evt_test_sub_deleted",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_test_123", "status": "canceled"}},
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.event_type == WebhookEventType.SUBSCRIPTION_CANCELLED

    def test_parse_invoice_payment_failed(self, adapter):
        """This is the key event for detecting subscription payment failures."""
        payload = {
            "id": "evt_test_inv_fail",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_test_123",
                    "subscription": "sub_test_123",
                    "amount_due": 999,
                    "currency": "usd",
                    "attempt_count": 1,
                    "next_payment_attempt": 1711900800,
                }
            },
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.event_type == WebhookEventType.SUBSCRIPTION_PAYMENT_FAILED
        assert event.payload["subscription"] == "sub_test_123"
        assert event.payload["attempt_count"] == 1

    def test_parse_invoice_payment_succeeded(self, adapter):
        payload = {
            "id": "evt_test_inv_ok",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_test_456",
                    "subscription": "sub_test_123",
                    "amount_paid": 999,
                    "currency": "usd",
                }
            },
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.event_type == WebhookEventType.SUBSCRIPTION_PAYMENT_SUCCEEDED


# ── Full payment flow via Stripe CLI ──


@skip_unless_stripe_cli
class TestStripeFullFlow:
    """End-to-end tests using ``stripe trigger`` to create completed payments.

    These tests require the Stripe CLI to be installed and authenticated.
    ``stripe trigger payment_intent.succeeded`` creates a real succeeded
    PaymentIntent in the test account that we can query and refund.
    """

    @pytest.fixture
    def succeeded_payment_intent(self, adapter):
        """Use Stripe CLI to create a succeeded PaymentIntent, return its ID."""
        result = subprocess.run(
            ["stripe", "trigger", "payment_intent.succeeded"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stripe trigger failed: {result.stderr}"

        # Fetch the PI ID from the most recent payment_intent.succeeded event
        data = adapter.client.http.call(
            "GET", "events", params={"type": "payment_intent.succeeded", "limit": "1"},
        )
        events = data.get("data", [])
        assert events, "No payment_intent.succeeded events found after stripe trigger"
        return events[0]["data"]["object"]["id"]

    def test_get_completed_payment(self, adapter, succeeded_payment_intent):
        result = adapter.get_payment(succeeded_payment_intent)
        assert isinstance(result, PaymentResult)
        assert result.payment_id == succeeded_payment_intent
        assert result.status == "completed"
        assert result.amount > 0

    def test_full_refund(self, adapter, succeeded_payment_intent):
        refund = adapter.refund(succeeded_payment_intent)
        assert isinstance(refund, Refund)
        assert refund.payment_id == succeeded_payment_intent
        assert refund.amount > 0
        assert refund.refund_id.startswith("re_")


# ── Subscription tests ──


class TestStripeSubscription:
    """Subscription checkout and management tests.

    Uses dynamically created Stripe prices for each test so there are
    no hard-coded price IDs to maintain.
    """

    @pytest.fixture
    def price_id(self, adapter):
        """Create a test recurring price and return its ID."""
        data = adapter.client.create_price(
            amount=999,
            currency="usd",
            interval="month",
            product_name="Integration Test Plan",
        )
        return data["id"]

    def test_adapter_supports_subscription_capability(self, adapter):
        assert adapter.supports(SubscriptionCapability)

    def test_create_subscription_checkout(self, adapter, price_id):
        session = adapter.create_subscription_checkout(
            price_id=price_id,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            customer_email="sub-test@example.com",
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id.startswith("cs_test_")
        assert "checkout.stripe.com" in session.payment_url
        assert session.extra.get("status") == "open"

    def test_create_subscription_checkout_with_trial(self, adapter, price_id):
        session = adapter.create_subscription_checkout(
            price_id=price_id,
            success_url="https://example.com/success",
            trial_days=14,
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id

    def test_create_subscription_checkout_with_metadata(self, adapter, price_id):
        session = adapter.create_subscription_checkout(
            price_id=price_id,
            success_url="https://example.com/success",
            metadata={"plan_tier": "premium", "source": "integration_test"},
        )
        assert isinstance(session, CheckoutSession)

    def test_get_nonexistent_subscription_raises(self, adapter):
        with pytest.raises(Exception):
            adapter.get_subscription("sub_nonexistent_12345")


@skip_unless_stripe_cli
class TestStripeSubscriptionFullFlow:
    """End-to-end subscription tests using ``stripe trigger``.

    ``stripe trigger customer.subscription.created`` creates a real active
    subscription in the test account that we can query, update, and cancel.
    """

    @pytest.fixture
    def active_subscription(self, adapter):
        """Use Stripe CLI to create an active subscription, return its ID."""
        result = subprocess.run(
            ["stripe", "trigger", "customer.subscription.created"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stripe trigger failed: {result.stderr}"

        # Fetch the subscription ID from the most recent event
        data = adapter.client.http.call(
            "GET", "events",
            params={"type": "customer.subscription.created", "limit": "1"},
        )
        events = data.get("data", [])
        assert events, "No customer.subscription.created events found"
        return events[0]["data"]["object"]["id"]

    def test_get_active_subscription(self, adapter, active_subscription):
        sub = adapter.get_subscription(active_subscription)
        assert isinstance(sub, Subscription)
        assert sub.subscription_id == active_subscription
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.amount > 0
        assert sub.currency
        assert sub.current_period_start is not None
        assert sub.current_period_end is not None
        assert sub.customer_id

    def test_cancel_subscription_at_period_end(self, adapter, active_subscription):
        sub = adapter.cancel_subscription(active_subscription, immediate=False)
        assert isinstance(sub, Subscription)
        assert sub.cancel_at_period_end is True
        assert sub.status == SubscriptionStatus.ACTIVE  # still active until period end

    def test_cancel_subscription_immediately(self, adapter, active_subscription):
        sub = adapter.cancel_subscription(active_subscription, immediate=True)
        assert isinstance(sub, Subscription)
        assert sub.status == SubscriptionStatus.CANCELLED


# ── Saved payment method tests ──


class TestStripeSavedPayment:
    """Customer creation, setup checkout, and payment method listing."""

    @pytest.fixture
    def customer_id(self, adapter):
        """Create a test customer and return the Stripe customer ID."""
        cid = adapter.create_customer(
            email="saved-card-test@example.com",
            name="Test Customer",
            metadata={"source": "integration_test"},
        )
        assert cid.startswith("cus_")
        return cid

    def test_adapter_supports_saved_payment_capability(self, adapter):
        assert adapter.supports(SavedPaymentCapability)

    def test_create_customer(self, adapter):
        cid = adapter.create_customer(email="new-customer@example.com")
        assert cid.startswith("cus_")

    def test_get_customer(self, adapter, customer_id):
        data = adapter.get_customer(customer_id)
        assert data["id"] == customer_id
        assert data["email"] == "saved-card-test@example.com"

    def test_create_setup_checkout(self, adapter, customer_id):
        session = adapter.create_setup_checkout(
            customer_id=customer_id,
            success_url="https://example.com/card-saved",
            cancel_url="https://example.com/cancel",
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id.startswith("cs_test_")
        assert "checkout.stripe.com" in session.payment_url

    def test_list_payment_methods_empty(self, adapter, customer_id):
        """New customer has no saved payment methods."""
        methods = adapter.list_payment_methods(customer_id)
        assert isinstance(methods, list)
        assert len(methods) == 0

    def test_get_nonexistent_customer_raises(self, adapter):
        with pytest.raises(Exception):
            adapter.get_customer("cus_nonexistent_12345")


@skip_unless_stripe_cli
class TestStripeSavedPaymentFullFlow:
    """End-to-end saved card tests using ``stripe trigger``.

    ``stripe trigger payment_method.attached`` creates a customer with an
    attached payment method that we can list, charge, and detach.
    """

    @pytest.fixture
    def customer_with_card(self, adapter):
        """Trigger a payment_method.attached event to get a customer with a card."""
        result = subprocess.run(
            ["stripe", "trigger", "payment_method.attached"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stripe trigger failed: {result.stderr}"

        data = adapter.client.http.call(
            "GET", "events",
            params={"type": "payment_method.attached", "limit": "1"},
        )
        events = data.get("data", [])
        assert events, "No payment_method.attached events found"
        pm = events[0]["data"]["object"]
        return {"customer_id": pm["customer"], "payment_method_id": pm["id"]}

    def test_list_payment_methods(self, adapter, customer_with_card):
        methods = adapter.list_payment_methods(customer_with_card["customer_id"])
        assert len(methods) >= 1
        pm = methods[0]
        assert isinstance(pm, SavedPaymentMethod)
        assert pm.payment_method_id.startswith("pm_")
        assert pm.last_four  # should have last 4 digits
        assert pm.card_brand != CardBrand.UNKNOWN
        assert pm.expiry_month is not None
        assert pm.expiry_year is not None

    def test_charge_saved_card(self, adapter, customer_with_card):
        result = adapter.charge_saved_method(
            customer_id=customer_with_card["customer_id"],
            payment_method_id=customer_with_card["payment_method_id"],
            amount=Decimal("15.00"),
            currency="USD",
            description="Saved card charge test",
        )
        assert isinstance(result, PaymentResult)
        assert result.status == "completed"
        assert result.amount == Decimal("15.00")
        assert result.payment_id.startswith("pi_")

    def test_set_default_and_verify(self, adapter, customer_with_card):
        success = adapter.set_default_payment_method(
            customer_with_card["customer_id"],
            customer_with_card["payment_method_id"],
        )
        assert success is True

        methods = adapter.list_payment_methods(customer_with_card["customer_id"])
        default_methods = [m for m in methods if m.is_default]
        assert len(default_methods) == 1
        assert default_methods[0].payment_method_id == customer_with_card["payment_method_id"]

    def test_delete_payment_method(self, adapter, customer_with_card):
        success = adapter.delete_payment_method(customer_with_card["payment_method_id"])
        assert success is True

        methods = adapter.list_payment_methods(customer_with_card["customer_id"])
        pm_ids = [m.payment_method_id for m in methods]
        assert customer_with_card["payment_method_id"] not in pm_ids
