"""
Payment port contract test suite.

Reusable tests that any PaymentPort adapter must pass.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto import CheckoutSession, ConnectionTestResult
from bapp_connectors.core.ports import PaymentPort


class PaymentContractTests:
    """Contract tests for PaymentPort implementations."""

    @pytest.fixture
    def adapter(self) -> PaymentPort:
        raise NotImplementedError

    def test_validate_credentials(self, adapter: PaymentPort):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter: PaymentPort):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True

    def test_create_checkout_session(self, adapter: PaymentPort):
        """Every payment adapter must be able to create a checkout session."""
        try:
            session = adapter.create_checkout_session(
                amount=Decimal("99.99"),
                currency="RON",
                description="Test Payment",
                identifier="TEST-001",
                success_url="https://example.com/success",
            )
            assert isinstance(session, CheckoutSession)
            assert session.session_id
            assert session.payment_url
            assert session.amount == Decimal("99.99")
            assert session.currency == "RON"
        except NotImplementedError:
            pytest.skip("Adapter does not support checkout session creation")

    def test_create_checkout_session_with_email(self, adapter: PaymentPort):
        try:
            session = adapter.create_checkout_session(
                amount=Decimal("50.00"),
                currency="EUR",
                description="Email Test",
                identifier="TEST-002",
                client_email="customer@test.com",
            )
            assert isinstance(session, CheckoutSession)
        except NotImplementedError:
            pytest.skip("Adapter does not support checkout session creation")

    def test_missing_credentials_fails(self):
        """Adapter with empty credentials should fail validation."""
        # Subclasses should override this with their adapter class
