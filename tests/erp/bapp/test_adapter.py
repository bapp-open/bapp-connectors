"""BAPP ERP provider tests, over a fake HTTP client."""

import json

import pytest
import requests

from bapp_connectors.core.dto import DeliveryStatus, MessageChannel, OutboundMessage
from bapp_connectors.core.errors import AuthenticationError, ConfigurationError, ConnectorError
from bapp_connectors.core.ports import ErpPort, MessagingPort
from bapp_connectors.core.registry import registry
from bapp_connectors.core.types import AuthStrategy, ProviderFamily
from bapp_connectors.providers.erp.bapp import BappErpAdapter, manifest
from bapp_connectors.providers.erp.bapp.errors import BappErpAuthError, BappErpError
from tests.erp.contract import ErpContractTests
from tests.fake_http import FakeHttpClient

TOKEN = "11111111-2222-3333-4444-555555555555"
CAPS = {
    "print": True,
    "sms": True,
    "devices": [
        {
            "id": "d1",
            "alias": "Reception",
            "printers": ["HP"],
            "default_printer": "HP",
            "last_active": "2026-10-20T10:00:00",
        }
    ],
    "phones": [{"id": "7", "label": "Work phone"}],
}


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def ok(data):
    # the ERP's real DirectTask wire shape (no "success" key); see wire_answer below
    return FakeResponse(200, wire_answer(True, "", data))


def wire_answer(success: bool, message: str, data: dict | None = None) -> dict:
    """What ``DirectTaskInterface.perform_action`` serializes for a ``DirectTaskResponse``.

    Copied from aio-backend application/bapp_framework/sdk/schema/tasks/interface.py
    (perform_action, ``result_data``): it answers HTTP 200 for a refused task too.
    """
    return {"finished": True, "message": str(message), "failed": not success, "data": data or {}}


def failed(message):
    return FakeResponse(200, wire_answer(False, message))


def make_adapter(http=None, **credentials):
    http = http or FakeHttpClient()
    creds = {"token": TOKEN, "tenant_id": "42", **credentials}
    return BappErpAdapter(credentials=creds, http_client=http), http


@pytest.fixture
def http():
    client = FakeHttpClient()
    client.add("POST", "tasks/company_device.BappCapabilities", ok(CAPS))
    client.add(
        "POST", "tasks/company_device.PrintFile", ok({"device": "d1", "device_alias": "Reception", "printer": "HP"})
    )
    client.add("POST", "tasks/company_sms.SendSms", ok({"phone": "7", "count": 1}))
    return client


class TestBappContract(ErpContractTests):
    @pytest.fixture
    def erp_adapter(self, http):
        return make_adapter(http)[0]


def test_manifest():
    assert manifest.name == "bapp"
    assert manifest.family == ProviderFamily.ERP == "erp"
    assert manifest.display_name == "BAPP"
    assert manifest.auth.strategy == AuthStrategy.TOKEN
    assert manifest.base_url == "https://panel.bapp.ro/api/"
    assert ErpPort in manifest.capabilities and MessagingPort in manifest.capabilities
    fields = {f.name: f for f in manifest.auth.required_fields}
    assert fields["token"].sensitive and fields["token"].required
    assert fields["tenant_id"].required


def test_registered():
    assert registry.get_adapter_class(ProviderFamily.ERP, "bapp") is BappErpAdapter


def test_print_posts_task_with_token_and_tenant_headers(http):
    adapter, _ = make_adapter(http)
    result = adapter.print_file("https://x.test/a.pdf", device="d1", printer="HP", copies=2)
    call = http.last_call()
    assert call.method == "POST"
    assert call.path == "https://panel.bapp.ro/api/tasks/company_device.PrintFile"
    assert call.kwargs["json"] == {"url": "https://x.test/a.pdf", "device": "d1", "printer": "HP", "copies": 2}
    assert call.kwargs["headers"]["X-Tenant-Id"] == "42"
    # set per request: the registry builds its client with a bare (prefix-less) TokenAuth
    assert call.kwargs["headers"]["Authorization"] == f"Token {TOKEN}"
    assert result == {"device": "d1", "device_alias": "Reception", "printer": "HP"}


def test_default_http_client_is_built_without_registry():
    adapter = BappErpAdapter(credentials={"token": TOKEN, "tenant_id": "42"})
    assert adapter.client.http.base_url == "https://panel.bapp.ro/api/"


def test_base_url_setting_overrides_default(http):
    adapter = BappErpAdapter(
        credentials={"token": TOKEN, "tenant_id": "42"},
        http_client=http,
        config={"base_url": "https://staging.bapp.ro/api"},
    )
    adapter.get_capabilities()
    assert http.last_call().path == "https://staging.bapp.ro/api/tasks/company_device.BappCapabilities"


def test_send_sms_posts_task(http):
    adapter, _ = make_adapter(http)
    assert adapter.send_sms(["+40700"], "hello", phone="7") == {"phone": "7", "count": 1}
    assert http.last_call().kwargs["json"] == {"recipients": ["+40700"], "body": "hello", "phone": "7"}


def test_task_failure_message_is_raised_verbatim():
    http = FakeHttpClient()
    http.add("POST", "company_device.PrintFile", failed("Nu exista nicio imprimanta activa."))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError) as exc:
        adapter.print_file("https://x.test/a.pdf")
    assert str(exc.value) == "Nu exista nicio imprimanta activa."


def test_http_error_message_is_raised_verbatim():
    http = FakeHttpClient()
    http.add("POST", "company_sms.SendSms", FakeResponse(400, {"message": "Numar invalid"}))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError) as exc:
        adapter.send_sms(["x"], "b")
    assert str(exc.value) == "Numar invalid"
    assert not isinstance(exc.value, BappErpAuthError)


def test_non_json_server_error_is_wrapped():
    http = FakeHttpClient()
    http.add("POST", "company_sms.SendSms", FakeResponse(502, text="Bad gateway"))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError, match="502"):
        adapter.send_sms(["x"], "b")


@pytest.mark.parametrize("status", [401, 403])
def test_401_raises_auth_error(status):
    http = FakeHttpClient()
    http.add("POST", "tasks/", FakeResponse(status, {"detail": "Invalid token."}))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpAuthError) as exc:
        adapter.get_capabilities()
    assert isinstance(exc.value, AuthenticationError)
    assert isinstance(exc.value, BappErpError)
    assert isinstance(exc.value, ConnectorError)


def test_send_maps_to_sms_task_and_returns_queued(http):
    adapter, _ = make_adapter(http)
    report = adapter.send(OutboundMessage(channel=MessageChannel.SMS, to="+40700", body="hi", message_id="m1"))
    assert report.status == DeliveryStatus.QUEUED
    assert report.message_id == "m1"
    assert http.last_call().kwargs["json"] == {"recipients": ["+40700"], "body": "hi", "phone": ""}


def test_send_failure_returns_failed_report():
    http = FakeHttpClient()
    http.add("POST", "company_sms.SendSms", failed("Nu exista telefon"))
    adapter, _ = make_adapter(http)
    report = adapter.send(OutboundMessage(channel=MessageChannel.SMS, to="+40700", body="hi"))
    assert report.status == DeliveryStatus.FAILED
    assert report.error == "Nu exista telefon"


def test_send_bulk_sends_each(http):
    adapter, _ = make_adapter(http)
    msgs = [OutboundMessage(channel=MessageChannel.SMS, to=f"+4070{i}", body="b") for i in range(3)]
    reports = adapter.send_bulk(msgs)
    assert [r.status for r in reports] == [DeliveryStatus.QUEUED] * 3
    assert len(http.calls) == 3


def test_test_connection_returns_capabilities_in_details(http):
    adapter, _ = make_adapter(http)
    result = adapter.test_connection()
    assert result.success is True
    assert result.details == {"capabilities": CAPS}


def test_test_connection_failure_reports_message():
    http = FakeHttpClient()
    http.add("POST", "tasks/", FakeResponse(401, {"detail": "Invalid token."}))
    adapter, _ = make_adapter(http)
    result = adapter.test_connection()
    assert result.success is False
    assert TOKEN not in result.message


def test_validate_credentials_requires_token_and_tenant():
    assert BappErpAdapter(credentials={"token": TOKEN}, http_client=FakeHttpClient()).validate_credentials() is False


def test_token_never_in_error_message_or_repr():
    http = FakeHttpClient()
    # a hostile/echoing server reflecting the Authorization header must not leak it either
    http.add("POST", "tasks/", FakeResponse(401, {"detail": f"bad token {TOKEN}"}))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError) as exc:
        adapter.get_capabilities()
    assert TOKEN not in str(exc.value)
    assert TOKEN not in repr(exc.value)
    assert TOKEN not in repr(adapter) and TOKEN not in repr(adapter.client)
    # (the fake http client records the request headers on purpose, so it is left out)
    assert TOKEN not in str({k: v for k, v in vars(adapter.client).items() if k != "http"})


# ── wire format (finding: the ERP answers "failed", not "success") ──


class TestDirectTaskWireContract:
    """Pins the adapter to what the ERP really sends for a DirectTask."""

    # Exactly what perform_action serializes for
    # DirectTaskResponse(success=False, message='Dispozitivul nu exista')
    # (aio-backend application/bapp_framework/sdk/schema/tasks/interface.py, perform_action):
    REFUSED = {"finished": True, "message": "Dispozitivul nu exista", "failed": True, "data": {}}

    def test_refused_task_raises_with_message_verbatim(self):
        http = FakeHttpClient()
        http.add("POST", "company_device.PrintFile", FakeResponse(200, dict(self.REFUSED)))
        adapter, _ = make_adapter(http)
        with pytest.raises(BappErpError) as exc:
            adapter.print_file("https://x.test/a.pdf", device="nope")
        assert str(exc.value) == "Dispozitivul nu exista"

    def test_refused_sms_is_a_failed_delivery(self):
        http = FakeHttpClient()
        http.add("POST", "company_sms.SendSms", FakeResponse(200, dict(self.REFUSED)))
        adapter, _ = make_adapter(http)
        report = adapter.send(OutboundMessage(channel=MessageChannel.SMS, to="+40700", body="hi"))
        assert report.status == DeliveryStatus.FAILED
        assert report.error == "Dispozitivul nu exista"

    def test_wire_answer_matches_the_refused_fixture(self):
        assert wire_answer(False, "Dispozitivul nu exista") == self.REFUSED

    def test_success_returns_data(self):
        http = FakeHttpClient()
        http.add(
            "POST",
            "company_device.PrintFile",
            FakeResponse(200, {"finished": True, "message": "ok", "failed": False, "data": {"device": "d1"}}),
        )
        adapter, _ = make_adapter(http)
        assert adapter.print_file("https://x.test/a.pdf") == {"device": "d1"}

    def test_legacy_success_false_also_raises(self):
        http = FakeHttpClient()
        http.add("POST", "company_device.PrintFile", FakeResponse(200, {"success": False, "message": "Nu"}))
        adapter, _ = make_adapter(http)
        with pytest.raises(BappErpError, match=r"^Nu$"):
            adapter.print_file("https://x.test/a.pdf")

    @pytest.mark.parametrize("body", [{"message": "", "data": {"device": "d1"}}, {"failed": None, "data": {}}, {}])
    def test_neither_failed_nor_success_fails_closed(self, body):
        http = FakeHttpClient()
        http.add("POST", "company_device.PrintFile", FakeResponse(200, body))
        adapter, _ = make_adapter(http)
        with pytest.raises(BappErpError, match="Unexpected BAPP response"):
            adapter.print_file("https://x.test/a.pdf")


# ── base_url allowlist (R11) ──


@pytest.mark.parametrize(
    "url",
    ["http://panel.bapp.ro/api/", "https://erp.test/api/", "https://bapp.ro.evil.test/api/", "https://evilbapp.ro/"],
)
def test_foreign_or_plain_http_base_url_is_refused_before_any_request(url):
    http = FakeHttpClient()
    http.add("POST", "tasks/", ok(CAPS))
    adapter = BappErpAdapter(
        credentials={"token": TOKEN, "tenant_id": "42"}, http_client=http, config={"base_url": url}
    )
    with pytest.raises(ConfigurationError) as exc:
        adapter.get_capabilities()
    with pytest.raises(ConfigurationError):
        adapter.print_file("https://x.test/a.pdf")
    with pytest.raises(ConfigurationError):
        adapter.send_sms(["+40700"], "hi")
    assert http.calls == []  # the token never left
    assert TOKEN not in str(exc.value)
    result = adapter.test_connection()
    assert result.success is False and http.calls == []
    report = adapter.send(OutboundMessage(channel=MessageChannel.SMS, to="+40700", body="hi"))
    assert report.status == DeliveryStatus.FAILED and http.calls == []


@pytest.mark.parametrize("url", ["https://panel.bapp.ro/api/", "https://staging.bapp.ro/api/", "https://bapp.ro/api/"])
def test_bapp_ro_base_urls_are_accepted(url):
    http = FakeHttpClient()
    http.add("POST", "tasks/", ok(CAPS))
    adapter = BappErpAdapter(
        credentials={"token": TOKEN, "tenant_id": "42"}, http_client=http, config={"base_url": url}
    )
    assert adapter.get_capabilities() == CAPS
    assert len(http.calls) == 1


# ── timeouts (print/SMS are not idempotent) ──


def _raiser(exc):
    def respond(method, path, kwargs):
        raise exc

    return respond


@pytest.mark.parametrize("call", ["print", "sms"])
def test_read_timeout_on_print_or_sms_says_outcome_unknown(call):
    http = FakeHttpClient()
    http.add("POST", "tasks/", _raiser(requests.ReadTimeout("read timed out")))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError) as exc:
        if call == "print":
            adapter.print_file("https://x.test/a.pdf")
        else:
            adapter.send_sms(["+40700"], "hi")
    assert "nu se stie daca s-a trimis" in str(exc.value)
    assert "nu retrimite" in str(exc.value)
    assert len(http.calls) == 1  # not resent


def test_connection_refused_is_not_reported_as_unknown_outcome():
    http = FakeHttpClient()
    http.add("POST", "tasks/", _raiser(requests.ConnectionError("refused")))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError) as exc:
        adapter.print_file("https://x.test/a.pdf")
    assert "unreachable" in str(exc.value)
    assert "nu se stie" not in str(exc.value)


def test_connect_timeout_is_unreachable_not_unknown():
    http = FakeHttpClient()
    http.add("POST", "tasks/", _raiser(requests.ConnectTimeout("connect timed out")))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError) as exc:
        adapter.send_sms(["+40700"], "hi")
    assert "unreachable" in str(exc.value) and "nu se stie" not in str(exc.value)


def test_timeout_on_capabilities_is_plain():
    http = FakeHttpClient()
    http.add("POST", "tasks/", _raiser(requests.ReadTimeout("read timed out")))
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError, match="nu a raspuns la timp") as exc:
        adapter.get_capabilities()
    assert "nu se stie" not in str(exc.value)
