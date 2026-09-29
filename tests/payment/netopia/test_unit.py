"""
Netopia unit tests — credential validation and adapter instantiation.

Netopia requires a live API key for checkout sessions, so we only test
credential validation and connection setup without network calls.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.dto.webhook import WebhookEventType
from bapp_connectors.core.errors import AuthenticationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.providers.payment.netopia.adapter import NetopiaPaymentAdapter
from bapp_connectors.providers.payment.netopia.errors import NetopiaOperationError
from bapp_connectors.providers.payment.netopia.manifest import manifest
from bapp_connectors.providers.payment.netopia.mappers import webhook_event_from_netopia
from tests.fake_http import FakeHttpClient


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

    def test_test_connection(self):
        fake = FakeHttpClient()
        fake.add("POST", "operation/status", {"error": {"code": "99", "message": "Invalid ntpID"}})
        a = NetopiaPaymentAdapter(credentials={"api_key": "k", "pos_signature": "s"}, http_client=fake)
        result = a.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True


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
    """Status codes from the official SDK (netopiapayments/composer IPN.php);
    real IPNs carry the status in ``payment.status``."""

    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (1, WebhookEventType.PAYMENT_PENDING),     # new
            (2, WebhookEventType.PAYMENT_PENDING),     # opened (pre-authorized)
            (3, WebhookEventType.PAYMENT_COMPLETED),   # paid
            (4, WebhookEventType.PAYMENT_FAILED),      # canceled (void)
            (5, WebhookEventType.PAYMENT_COMPLETED),   # confirmed
            (8, WebhookEventType.PAYMENT_REFUNDED),    # credit
            (12, WebhookEventType.PAYMENT_FAILED),     # declined
            (15, WebhookEventType.PAYMENT_PENDING),    # 3-D Secure required, not a refund
            (23, WebhookEventType.PAYMENT_FAILED),     # expired
        ],
    )
    def test_ipn_status_maps_to_payment_event(self, status_code, expected):
        event = webhook_event_from_netopia({"payment": {"ntpID": "NTP1", "status": status_code}})
        assert event.event_type == expected
        assert event.provider == "netopia"
        assert event.event_id == "NTP1"
        assert event.provider_event_type.startswith("payment.")

    def test_top_level_status_still_read(self):
        event = webhook_event_from_netopia({"status": 5, "payment": {"ntpID": "NTP1"}})
        assert event.event_type == WebhookEventType.PAYMENT_COMPLETED

    def test_unknown_status_is_unknown(self):
        event = webhook_event_from_netopia({"payment": {"status": 999}})
        assert event.event_type == WebhookEventType.UNKNOWN

    def test_refund_after_payment_is_not_a_duplicate(self):
        paid = webhook_event_from_netopia({"payment": {"ntpID": "NTP1", "status": 3}})
        confirmed = webhook_event_from_netopia({"payment": {"ntpID": "NTP1", "status": 5}})
        refunded = webhook_event_from_netopia({"payment": {"ntpID": "NTP1", "status": 8}})
        assert paid.idempotency_key == confirmed.idempotency_key
        assert refunded.idempotency_key != paid.idempotency_key


class TestNetopiaBaseUrl:
    """The registry always injects a client built from manifest.base_url; the
    adapter must re-point it per the sandbox flag."""

    def _adapter(self, sandbox: str) -> NetopiaPaymentAdapter:
        injected = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth())
        return NetopiaPaymentAdapter(
            credentials={"api_key": "k", "pos_signature": "s", "sandbox": sandbox},
            http_client=injected,
        )

    def test_live_points_at_mobilpay_api(self):
        # secure.netopia-payments.com is the marketing site and 302s every call.
        assert self._adapter("false").client.http.base_url == "https://secure.mobilpay.ro/pay/"

    def test_sandbox_points_at_sandbox_api(self):
        assert self._adapter("true").client.http.base_url == "https://secure.sandbox.netopia-payments.com/"


class TestNetopiaTestAuth:

    def _adapter(self, response) -> tuple[NetopiaPaymentAdapter, FakeHttpClient]:
        fake = FakeHttpClient()
        fake.add("POST", "operation/status", response)
        a = NetopiaPaymentAdapter(credentials={"api_key": "k", "pos_signature": "SIG-1"}, http_client=fake)
        return a, fake

    def test_uses_authenticated_endpoint_not_healz(self):
        a, fake = self._adapter({"error": {"code": "99", "message": "Invalid ntpID"}})
        assert a.client.test_auth() is True
        assert [c.path for c in fake.calls] == ["operation/status"]

    def test_rejected_key_is_false(self):
        def unauthorized(method, path, kwargs):
            raise AuthenticationError("Authentication failed: 401", status_code=401)

        a, _ = self._adapter(unauthorized)
        assert a.client.test_auth() is False
        assert a.test_connection().success is False

    def test_transport_error_surfaces_message(self):
        def down(method, path, kwargs):
            raise ConnectionError("DNS failure")

        a, _ = self._adapter(down)
        result = a.test_connection()
        assert result.success is False
        assert "DNS failure" in result.message


# The shape Netopia really returns for an unknown order (captured from live).
NOT_FOUND = {"error": {"code": "103", "message": "Unable to retrieve order information"},
             "payment": {"amount": 0, "status": 0}}


def _adapter_with(*rules) -> tuple[NetopiaPaymentAdapter, FakeHttpClient]:
    fake = FakeHttpClient()
    for path, response in rules:
        fake.add("POST", path, response)
    a = NetopiaPaymentAdapter(credentials={"api_key": "k", "pos_signature": "SIG-1"}, http_client=fake)
    return a, fake


def _status(code: int, amount: float = 50.0) -> dict:
    return {"error": {"code": "00", "message": "Approved"},
            "payment": {"ntpID": "NTP1", "status": code, "amount": amount, "currency": "RON"},
            "order": {"orderID": "O-1"}}


class TestNetopiaRefund:

    def test_refused_refund_raises_instead_of_reporting_completed(self):
        a, _ = _adapter_with(("operation/credit", NOT_FOUND))
        with pytest.raises(NetopiaOperationError) as exc:
            a.refund("NTP1", Decimal("10"))
        assert exc.value.code == "103"
        assert exc.value.retryable is False

    def test_partial_refund_reports_requested_amount(self):
        a, fake = _adapter_with(("operation/credit", _status(8)))
        refund = a.refund("NTP1", Decimal("10.50"))
        assert refund.amount == Decimal("10.50")
        assert refund.status == "completed"
        assert refund.extra["payment_status"] == "refunded"
        assert b'"amount": 10.5' in fake.calls[0].kwargs["data"]

    def test_full_refund_reports_payment_amount(self):
        a, _ = _adapter_with(("operation/credit", _status(8, amount=50.0)))
        assert a.refund("NTP1").amount == Decimal("50.0")


class TestNetopiaGetPayment:

    def test_status_read_from_payment_object(self):
        a, _ = _adapter_with(("operation/status", _status(5, amount=12.34)))
        result = a.get_payment("NTP1")
        assert result.status == "completed"
        assert result.amount == Decimal("12.34")
        assert result.extra["netopia_status"] == "confirmed"

    def test_status_sends_pos_id_like_official_sdk(self):
        a, fake = _adapter_with(("operation/status", _status(5)))
        a.get_payment("NTP1")
        assert b'"posID": "SIG-1"' in fake.calls[0].kwargs["data"]

    def test_unknown_payment_raises(self):
        a, _ = _adapter_with(("operation/status", NOT_FOUND))
        with pytest.raises(NetopiaOperationError):
            a.get_payment("NTP1")


class TestNetopiaCancel:

    def test_preauthorized_payment_is_voided(self):
        a, fake = _adapter_with(("operation/status", _status(2)), ("operation/void", _status(4)))
        assert a.cancel_payment("NTP1").status == "cancelled"
        assert [c.path for c in fake.calls] == ["operation/status", "operation/void"]

    def test_unpaid_payment_is_expired_with_pos_id(self):
        a, fake = _adapter_with(("operation/status", _status(1)), ("operation/expire", _status(23)))
        assert a.cancel_payment("NTP1").status == "cancelled"
        assert fake.calls[1].path == "operation/expire"
        assert b'"posID": "SIG-1"' in fake.calls[1].kwargs["data"]

    def test_captured_payment_must_be_refunded(self):
        a, fake = _adapter_with(("operation/status", _status(3)))
        with pytest.raises(NetopiaOperationError, match="refund it instead"):
            a.cancel_payment("NTP1")
        assert [c.path for c in fake.calls] == ["operation/status"]

    def test_refused_void_raises(self):
        a, _ = _adapter_with(("operation/status", _status(2)), ("operation/void", NOT_FOUND))
        with pytest.raises(NetopiaOperationError):
            a.cancel_payment("NTP1")


class TestNetopiaCheckout:

    def test_redirect_code_is_not_an_error(self):
        a, _ = _adapter_with(("payment/card/start", {
            "error": {"code": "101", "message": "Redirect user to payment page"},
            "payment": {"ntpID": "NTP9", "paymentURL": "https://pay/x", "status": 1},
        }))
        session = a.create_checkout_session(Decimal("1"), "RON", "d", "O-1")
        assert session.payment_url == "https://pay/x"

    def test_refused_start_raises(self):
        a, _ = _adapter_with(("payment/card/start", {"error": {"code": "19", "message": "Invalid signature"}}))
        with pytest.raises(NetopiaOperationError):
            a.create_checkout_session(Decimal("1"), "RON", "d", "O-1")
