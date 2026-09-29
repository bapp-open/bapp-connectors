"""What arrives from and goes to a payment processor stays visible.

- ExecutionLog keeps response bodies (they were never stored: ResponseContext.body
  was always None) for failures and for calls marked `log_body=True`.
- The form-based payment adapters (LibraPay…) keep their http client as
  `_http_client`; their calls — refunds included — were never logged.
- A webhook that fails signature verification is stored as "rejected".
- A form IPN stored as {"raw": ...} is re-parsed from the form, not from that dict.
"""
import json
from types import SimpleNamespace
from unittest import mock

import pytest
import responses

from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from django_bapp_connectors.callbacks import make_execution_log_callback
from django_bapp_connectors.services.connection import EXECUTION_LOG_MARKER, ConnectionService, resolve_http_client
from django_bapp_connectors.services.webhook import WebhookService, stored_webhook_body

from tests.testapp.models import Connection, ExecutionLog, WebhookEvent

URL = "https://secure.librapay.test/pay_sales.php"


@pytest.fixture
def connection(db):
    return Connection.objects.create(provider_family="payment", provider_name="librapay", display_name="LibraPay")


def _logged_client(connection):
    client = ResilientHttpClient(base_url="https://secure.librapay.test/", auth=NoAuth())
    on_response, on_error = make_execution_log_callback(ExecutionLog, connection)
    client.middleware.add_on_response(on_response)
    client.middleware.add_on_error(on_error)
    return client


# ── ExecutionLog bodies ──


@responses.activate
def test_a_flagged_2xx_keeps_its_answer(connection):
    responses.add(responses.POST, URL, body="Tranzactie procesata", status=200)
    _logged_client(connection).call("POST", URL, data={"ORDER": "100001"}, log_body=True, direct_response=True)
    log = ExecutionLog.objects.get()
    assert log.response_payload == "Tranzactie procesata"
    assert log.request_payload == {"ORDER": "100001"}


@responses.activate
def test_an_ordinary_2xx_keeps_metadata_only(connection):
    responses.add(responses.GET, URL, json={"products": [1, 2, 3]}, status=200)
    _logged_client(connection).call("GET", URL)
    log = ExecutionLog.objects.get()
    assert log.response_status == 200
    assert log.response_payload is None and log.request_payload is None


@responses.activate
def test_a_failure_now_keeps_the_response_body(connection):
    responses.add(responses.POST, URL, json={"code": "400", "message": "Validation error"}, status=400)
    with pytest.raises(Exception):
        _logged_client(connection).call("POST", URL, json={})
    assert ExecutionLog.objects.get().response_payload == {"code": "400", "message": "Validation error"}


@responses.activate
def test_a_json_bytes_request_is_redacted(connection):
    """Netopia posts bytes; its POS signature and api key must not reach the log."""
    responses.add(responses.POST, URL, json={"error": {"code": "103"}}, status=200)
    body = json.dumps({"posID": "30AD-SECRET", "ntpID": "1", "api_key": "k"}).encode()
    _logged_client(connection).call("POST", URL, data=body, log_body=True)
    assert ExecutionLog.objects.get().request_payload == {"posID": "***", "ntpID": "1", "api_key": "***"}


# ── Which http client gets the logger ──


def test_the_private_http_client_of_form_based_payment_adapters_is_found():
    http = ResilientHttpClient(base_url="https://x.test/", auth=NoAuth())
    assert resolve_http_client(SimpleNamespace(_http_client=http)) is http
    assert resolve_http_client(SimpleNamespace(_client=SimpleNamespace(http=http))) is http
    assert resolve_http_client(SimpleNamespace(client=SimpleNamespace(http=http))) is http
    assert resolve_http_client(SimpleNamespace()) is None


def test_the_logger_is_attached_once(connection):
    http = ResilientHttpClient(base_url="https://x.test/", auth=NoAuth())
    adapter = SimpleNamespace(_http_client=http)
    with mock.patch("django_bapp_connectors.services.connection.registry.create_adapter", return_value=adapter):
        ConnectionService.get_adapter(connection)
        ConnectionService.get_adapter(connection)
    assert getattr(http, EXECUTION_LOG_MARKER) is True
    assert len(http.middleware._on_response) == 1  # a second attach would log every call twice


# ── Rejected webhooks ──


def test_a_webhook_failing_verification_is_stored_as_rejected(connection):
    service = WebhookService(webhook_event_model=WebhookEvent)
    received = mock.Mock()
    with mock.patch("django_bapp_connectors.signals.webhook_event_received.send_robust", received):
        with pytest.raises(WebhookVerificationError):
            service.receive(
                provider="librapay", headers={"Cookie": "s=1", "X-Test": "a"}, body=b"ORDER=1&P_SIGN=forged",
                signature_method="hmac-sha1", signature_header="X-Sig", secret="k", connection=connection,
            )
    row = WebhookEvent.objects.get()
    assert (row.status, row.signature_valid) == ("rejected", False)
    assert row.payload == {"raw": "ORDER=1&P_SIGN=forged"}
    assert "Cookie" not in row.headers and row.headers["X-Test"] == "a"
    assert row.error
    received.assert_not_called()  # a forged IPN must not start anything


def test_rejected_rows_do_not_block_a_genuine_retry(connection):
    service = WebhookService(webhook_event_model=WebhookEvent)
    for _ in range(2):
        with pytest.raises(WebhookVerificationError):
            service.receive(provider="librapay", headers={}, body=b"ORDER=1", signature_method="hmac-sha1",
                            signature_header="X-Sig", secret="k", connection=connection)
    assert WebhookEvent.objects.filter(status="rejected").count() == 2


def test_a_huge_rejected_body_is_capped(connection):
    service = WebhookService(webhook_event_model=WebhookEvent)
    with pytest.raises(WebhookVerificationError):
        service.receive(provider="librapay", headers={}, body=b"x" * 100_000, signature_method="hmac-sha1",
                        signature_header="X-Sig", secret="k", connection=connection)
    assert len(WebhookEvent.objects.get().payload["raw"]) == 16000


# ── Re-parsing a stored form IPN ──


def test_a_stored_form_body_is_rebuilt_as_the_form():
    assert stored_webhook_body({"raw": "ORDER=1&DESC=checkout-x"}) == b"ORDER=1&DESC=checkout-x"
    assert json.loads(stored_webhook_body({"order": {"id": 1}})) == {"order": {"id": 1}}
    assert stored_webhook_body(None) == b""
