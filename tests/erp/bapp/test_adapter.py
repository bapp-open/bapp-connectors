"""BAPP ERP provider tests, over a fake HTTP client."""

import json

import pytest

from bapp_connectors.core.dto import DeliveryStatus, MessageChannel, OutboundMessage
from bapp_connectors.core.errors import AuthenticationError, ConnectorError
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
    return FakeResponse(200, {"success": True, "message": "", "data": data})


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
        credentials={"token": TOKEN, "tenant_id": "42"}, http_client=http, config={"base_url": "https://erp.test/api"}
    )
    adapter.get_capabilities()
    assert http.last_call().path == "https://erp.test/api/tasks/company_device.BappCapabilities"


def test_send_sms_posts_task(http):
    adapter, _ = make_adapter(http)
    assert adapter.send_sms(["+40700"], "hello", phone="7") == {"phone": "7", "count": 1}
    assert http.last_call().kwargs["json"] == {"recipients": ["+40700"], "body": "hello", "phone": "7"}


def test_task_failure_message_is_raised_verbatim():
    http = FakeHttpClient()
    http.add(
        "POST",
        "company_device.PrintFile",
        FakeResponse(200, {"success": False, "message": "Nu exista nicio imprimanta activa."}),
    )
    adapter, _ = make_adapter(http)
    with pytest.raises(BappErpError) as exc:
        adapter.print_file("https://x.test/a.pdf")
    assert str(exc.value) == "Nu exista nicio imprimanta activa."


def test_http_error_message_is_raised_verbatim():
    http = FakeHttpClient()
    http.add("POST", "company_sms.SendSms", FakeResponse(400, {"success": False, "message": "Numar invalid"}))
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
    http.add("POST", "company_sms.SendSms", FakeResponse(200, {"success": False, "message": "Nu exista telefon"}))
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
