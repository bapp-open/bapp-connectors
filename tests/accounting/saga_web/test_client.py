"""SagaWebApiClient: headers, absolute URLs, multipart Import, refresh-token capture, errors."""

from __future__ import annotations

import json

import pytest
import requests

from bapp_connectors.providers.accounting.saga_web.client import SagaWebApiClient
from bapp_connectors.providers.accounting.saga_web.errors import (
    SagaWebAuthError,
    SagaWebCredentialsNotSaved,
    SagaWebError,
    SagaWebValidationError,
)
from tests.fake_http import FakeHttpClient

BASE = "https://web2.sagasoft.ro/sagac/api/v20260225/"


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def ok_envelope(data="", headers=None):
    return FakeResponse(200, {"success": True, "message": "", "data": data}, headers=headers)


def make_client(http, callback=None, token="K1"):
    return SagaWebApiClient(http, token=token, cod_fiscal="6716875", base_url=BASE, on_credentials_update=callback)


def test_headers_and_absolute_url():
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", ok_envelope("12.50"))
    client = make_client(http)
    assert client.get_json("Situatii/GetSoldCont", {"cont": "5121"}) == (True, "", "12.50")
    call = http.last_call()
    assert call.path == "https://web2.sagasoft.ro/sagac/api/v20260225/Situatii/GetSoldCont"
    assert "fake.local" not in call.path
    assert call.kwargs["headers"]["Authorization"] == "Bearer K1"
    assert call.kwargs["headers"]["X-Saga-Cod-Fiscal"] == "6716875"
    assert call.kwargs["params"] == {"cont": "5121"}
    assert call.kwargs["direct_response"] is True


def test_import_is_multipart_and_not_retried():
    http = FakeHttpClient()
    http.add("POST", "Import", FakeResponse(200, text="Raport Import"))
    client = make_client(http)
    response = client.import_file("F_x.xml", b"<Facturi/>", auto_import=True)
    assert response.text == "Raport Import"
    call = http.last_call()
    assert call.method == "POST"
    assert call.path == BASE + "Import"
    assert call.kwargs["files"]["file"] == ("F_x.xml", b"<Facturi/>", "application/xml")
    assert call.kwargs["data"] == {"importAutomat": "true"}
    assert call.kwargs["retry"] is False
    assert call.kwargs["direct_response"] is True
    assert call.kwargs["headers"]["Authorization"] == "Bearer K1"


def test_import_auto_import_false():
    http = FakeHttpClient()
    http.add("POST", "Import", FakeResponse(200, text="ok"))
    make_client(http).import_file("F_x.xml", b"<Facturi/>", auto_import=False)
    assert http.last_call().kwargs["data"] == {"importAutomat": "false"}


def test_refresh_token_captured_on_200_and_callback_called():
    updates = []
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", ok_envelope("1", headers={"X-Saga-Refresh-Token": "K2"}))
    client = make_client(http, callback=updates.append)
    client.get_json("Situatii/GetSoldCont", {})
    assert client.token == "K2"
    assert updates == [{"token": "K2"}]
    http.responses.clear()
    http.add("GET", "GetSoldCont", ok_envelope("1"))
    client.get_json("Situatii/GetSoldCont", {})
    assert http.last_call().kwargs["headers"]["Authorization"] == "Bearer K2"
    assert updates == [{"token": "K2"}]


def test_refresh_header_lookup_is_case_insensitive():
    updates = []
    http = FakeHttpClient()
    http.add("GET", "X", ok_envelope("1", headers={"x-saga-refresh-token": "K2"}))
    client = make_client(http, callback=updates.append)
    client.get_json("X", {})
    assert client.token == "K2"
    assert updates == [{"token": "K2"}]


def test_refresh_token_captured_on_422():
    updates = []
    http = FakeHttpClient()
    http.add(
        "POST",
        "Import",
        FakeResponse(422, text="Raport Import\nFactura 1.\nEroare: x", headers={"X-Saga-Refresh-Token": "K2"}),
    )
    client = make_client(http, callback=updates.append)
    response = client.import_file("F_x.xml", b"<Facturi/>", auto_import=True)
    assert response.status_code == 422
    assert updates == [{"token": "K2"}]
    assert client.token == "K2"


def test_refresh_token_captured_on_401_before_raising():
    updates = []
    http = FakeHttpClient()
    http.add("GET", "X", FakeResponse(401, text="", headers={"X-Saga-Refresh-Token": "K2"}))
    client = make_client(http, callback=updates.append)
    with pytest.raises(SagaWebAuthError):
        client.get_json("X", {})
    assert updates == [{"token": "K2"}]


def test_same_token_does_not_call_callback():
    updates = []
    http = FakeHttpClient()
    http.add("GET", "X", ok_envelope("1", headers={"X-Saga-Refresh-Token": "K1"}))
    client = make_client(http, callback=updates.append)
    client.get_json("X", {})
    assert updates == []
    assert client.token == "K1"


def test_empty_refresh_header_is_ignored():
    updates = []
    http = FakeHttpClient()
    http.add("GET", "X", ok_envelope("1", headers={"X-Saga-Refresh-Token": "  "}))
    client = make_client(http, callback=updates.append)
    client.get_json("X", {})
    assert updates == []
    assert client.token == "K1"


def test_refresh_without_callback_still_updates_token():
    http = FakeHttpClient()
    http.add("GET", "X", ok_envelope("1", headers={"X-Saga-Refresh-Token": "K2"}))
    client = make_client(http)
    client.get_json("X", {})
    assert client.token == "K2"


@pytest.mark.parametrize("status", [401, 403])
def test_401_raises_auth_error_without_leaking_key(status):
    http = FakeHttpClient()
    http.add("GET", "X", FakeResponse(status, text="Unauthorized K1"))
    client = make_client(http)
    with pytest.raises(SagaWebAuthError) as exc_info:
        client.get_json("X", {})
    assert "K1" not in str(exc_info.value)
    assert exc_info.value.status_code == status
    assert exc_info.value.retryable is False


def test_transport_error_wrapped():
    def boom(method, path, kwargs):
        raise requests.ConnectionError("Bearer K1 refused")

    http = FakeHttpClient()
    http.add("GET", "X", boom)
    with pytest.raises(SagaWebError) as exc_info:
        make_client(http).get_json("X", {})
    assert "ConnectionError" in str(exc_info.value)
    assert "K1" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_connect_timeout_message():
    def boom(method, path, kwargs):
        raise requests.ConnectTimeout("x")

    http = FakeHttpClient()
    http.add("POST", "Import", boom)
    with pytest.raises(SagaWebError, match=r"SAGA Web nu răspunde \(ConnectTimeout\)"):
        make_client(http).import_file("F_x.xml", b"<Facturi/>", auto_import=True)


def test_import_timeout_message_says_unknown_outcome():
    def boom(method, path, kwargs):
        raise requests.ReadTimeout("x")

    http = FakeHttpClient()
    http.add("POST", "Import", boom)
    with pytest.raises(SagaWebError) as exc_info:
        make_client(http).import_file("F_x.xml", b"<Facturi/>", auto_import=True)
    assert "nu retrimite automat" in str(exc_info.value)
    assert exc_info.value.retryable is False
    assert str(exc_info.value) == (
        "SAGA Web nu a răspuns la timp; nu se știe dacă fișierul a fost primit — nu retrimite automat"
    )


def test_get_json_400_is_validation_error():
    http = FakeHttpClient()
    http.add(
        "GET",
        "X",
        FakeResponse(400, {"success": False, "error": "Data trebuie sa fie in formatul dd.MM.yyyy."}),
    )
    with pytest.raises(SagaWebValidationError) as exc_info:
        make_client(http).get_json("X", {"data": "2026-01-01"})
    assert str(exc_info.value) == "Data trebuie sa fie in formatul dd.MM.yyyy."
    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False


def test_get_json_5xx_raises_saga_web_error():
    http = FakeHttpClient()
    http.add("GET", "X", FakeResponse(500, {"success": False, "message": "Eroare interna"}))
    with pytest.raises(SagaWebError) as exc_info:
        make_client(http).get_json("X", {})
    assert not isinstance(exc_info.value, SagaWebValidationError)
    assert exc_info.value.status_code == 500
    assert str(exc_info.value) == "Eroare interna"


def test_get_json_5xx_non_json_body_uses_status_message():
    http = FakeHttpClient()
    http.add("GET", "X", FakeResponse(502, text=""))
    with pytest.raises(SagaWebError, match="SAGA Web a răspuns cu HTTP 502") as exc_info:
        make_client(http).get_json("X", {})
    assert exc_info.value.status_code == 502


def test_get_json_200_success_false_returns_tuple():
    http = FakeHttpClient()
    http.add("GET", "X", FakeResponse(200, {"success": False, "message": "Cont inexistent"}))
    assert make_client(http).get_json("X", {}) == (False, "Cont inexistent", "")


def test_get_xml_200_returns_text():
    http = FakeHttpClient()
    http.add("GET", "Balanta", FakeResponse(200, text="<Balanta/>"))
    assert make_client(http).get_xml("Situatii/Balanta", {"luna": 1}) == "<Balanta/>"


def test_get_xml_400_is_validation_error():
    http = FakeHttpClient()
    http.add("GET", "Balanta", FakeResponse(400, {"success": False, "message": "Luna invalida"}))
    with pytest.raises(SagaWebValidationError, match="Luna invalida"):
        make_client(http).get_xml("Situatii/Balanta", {})


def test_get_xml_500_is_provider_error_with_status():
    http = FakeHttpClient()
    http.add("GET", "Balanta", FakeResponse(500, {"success": False, "message": "Eroare interna"}))
    with pytest.raises(SagaWebError) as exc_info:
        make_client(http).get_xml("Situatii/Balanta", {})
    assert not isinstance(exc_info.value, SagaWebValidationError)
    assert exc_info.value.status_code == 500
    assert "Eroare interna" in str(exc_info.value)


def test_repr_hides_token():
    client = make_client(FakeHttpClient())
    assert "K1" not in repr(client)
    assert "K1" not in repr(vars(client))


def test_invalid_header_value_error_never_carries_the_key():
    def boom(method, path, kwargs):
        raise ValueError("Invalid leading whitespace, reserved character(s), or return character(s) in header value: 'Bearer KEY\\nX'")

    http = FakeHttpClient()
    http.add("GET", "X", boom)
    with pytest.raises(SagaWebError) as exc_info:
        make_client(http, token="KEY\nX").get_json("X", {})
    assert str(exc_info.value) == "Credențiale SAGA Web invalide (ValueError)"
    assert "KEY" not in str(exc_info.value)
    assert exc_info.value.retryable is False
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_token_trailing_newline_is_stripped():
    http = FakeHttpClient()
    http.add("GET", "X", ok_envelope("1"))
    client = SagaWebApiClient(http, token="KEY\n", cod_fiscal=" 6716875 ", base_url=BASE)
    client.get_json("X", {})
    headers = http.last_call().kwargs["headers"]
    assert headers["Authorization"] == "Bearer KEY"
    assert headers["X-Saga-Cod-Fiscal"] == "6716875"


def test_import_timeout_is_180_reads_keep_default():
    http = FakeHttpClient()
    http.add("POST", "Import", FakeResponse(200, text="ok"))
    http.add("GET", "X", ok_envelope("1"))
    client = make_client(http)
    client.import_file("F_x.xml", b"<Facturi/>", auto_import=True)
    assert http.last_call().kwargs["timeout"] == 180
    client.get_json("X", {})
    assert "timeout" not in http.last_call().kwargs


@pytest.mark.parametrize(
    "exc", [requests.ConnectionError("reset"), requests.ConnectTimeout("x"), requests.ReadTimeout("x"), ValueError("x")]
)
def test_every_import_transport_error_is_not_retryable(exc):
    def boom(method, path, kwargs):
        raise exc

    http = FakeHttpClient()
    http.add("POST", "Import", boom)
    with pytest.raises(SagaWebError) as exc_info:
        make_client(http).import_file("F_x.xml", b"<Facturi/>", auto_import=True)
    assert exc_info.value.retryable is False


def test_read_connection_error_stays_retryable():
    def boom(method, path, kwargs):
        raise requests.ConnectionError("reset")

    http = FakeHttpClient()
    http.add("GET", "X", boom)
    with pytest.raises(SagaWebError) as exc_info:
        make_client(http).get_json("X", {})
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("status", [200, 401])
def test_failing_callback_raises_credentials_not_saved_without_the_key(status):
    def callback(patch):
        raise RuntimeError(f"db down while saving {patch['token']}")

    http = FakeHttpClient()
    http.add("GET", "X", FakeResponse(status, {"success": True, "data": "1"}, headers={"X-Saga-Refresh-Token": "NEWKEY9"}))
    with pytest.raises(SagaWebCredentialsNotSaved) as exc_info:
        make_client(http, callback=callback).get_json("X", {})
    exc = exc_info.value
    assert str(exc) == "Cheia nouă SAGA Web nu a putut fi salvată; rularea trebuie oprită"
    assert "NEWKEY9" not in str(exc)
    assert exc.retryable is False
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True
    # no client frame of the raising traceback keeps the key in a local (skip this test's frame)
    tb = exc.__traceback__.tb_next
    assert tb is not None
    while tb is not None:
        assert "NEWKEY9" not in repr(tb.tb_frame.f_locals)
        tb = tb.tb_next
