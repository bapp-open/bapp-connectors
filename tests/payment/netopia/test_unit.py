"""
Netopia unit tests — credential validation and adapter instantiation.

Netopia requires a live API key for checkout sessions, so we only test
credential validation and connection setup without network calls.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.dto.webhook import WebhookEventType
from bapp_connectors.providers.payment.netopia.adapter import NetopiaPaymentAdapter
from bapp_connectors.providers.payment.netopia.mappers import webhook_event_from_netopia


@pytest.fixture
def adapter():
    return NetopiaPaymentAdapter(credentials={
        "api_key": "test_api_key_123",
        "pos_signature": "test_pos_sig",
        "sandbox": "true",
    })


class TestNetopiaContract:
    from tests.payment.contract import PaymentContractTests

    # Only run credential/connection tests (checkout needs live API)
    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        # Will fail without real key, but should not crash
        assert isinstance(result.success, bool)


class TestNetopiaCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True
        assert adapter.sandbox is True

    def test_missing_api_key(self):
        a = NetopiaPaymentAdapter(credentials={"pos_signature": "sig"})
        assert a.validate_credentials() is False

    def test_missing_pos_signature(self):
        a = NetopiaPaymentAdapter(credentials={"api_key": "key"})
        assert a.validate_credentials() is False

    def test_sandbox_mode(self):
        a = NetopiaPaymentAdapter(credentials={
            "api_key": "key", "pos_signature": "sig", "sandbox": "true",
        })
        assert a.sandbox is True

    def test_live_mode(self):
        a = NetopiaPaymentAdapter(credentials={
            "api_key": "key", "pos_signature": "sig", "sandbox": "false",
        })
        assert a.sandbox is False

    def test_config_urls(self):
        a = NetopiaPaymentAdapter(
            credentials={"api_key": "k", "pos_signature": "s"},
            config={"notify_url": "https://my.com/ipn", "redirect_url": "https://my.com/ok"},
        )
        assert a.client.notify_url == "https://my.com/ipn"
        assert a.client.redirect_url == "https://my.com/ok"


class TestNetopiaWebhookMapping:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (0, WebhookEventType.PAYMENT_PENDING),    # pending
            (3, WebhookEventType.PAYMENT_PENDING),    # paid_pending
            (5, WebhookEventType.PAYMENT_COMPLETED),  # confirmed
            (12, WebhookEventType.PAYMENT_FAILED),    # cancelled
            (15, WebhookEventType.PAYMENT_REFUNDED),  # credit
        ],
    )
    def test_ipn_status_maps_to_payment_event(self, status_code, expected):
        event = webhook_event_from_netopia(
            {"status": status_code, "payment": {"ntpID": "NTP1"}}
        )
        assert event.event_type == expected
        assert event.provider == "netopia"
        assert event.event_id == "NTP1"
        assert event.provider_event_type.startswith("payment.")

    def test_unknown_status_is_unknown(self):
        event = webhook_event_from_netopia({"status": 999})
        assert event.event_type == WebhookEventType.UNKNOWN
