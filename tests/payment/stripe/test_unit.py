"""
Stripe unit tests — credential validation and adapter instantiation.

Stripe requires a live API key for operations, so we test setup without network.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.providers.payment.stripe.adapter import StripePaymentAdapter


@pytest.fixture
def adapter():
    return StripePaymentAdapter(credentials={
        "secret_key": "sk_test_123456789",
    })


class TestStripeCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_secret_key(self):
        a = StripePaymentAdapter(credentials={})
        assert a.validate_credentials() is False

    def test_test_connection_returns_result(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert isinstance(result.success, bool)

    def test_adapter_stores_key(self, adapter):
        assert adapter.secret_key == "sk_test_123456789"
