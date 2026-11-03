"""SAGA Web over a real ``ResilientHttpClient`` (``responses`` intercepts the socket).

The fake transport in the other tests records kwargs; these check what requests actually does
with them: the refresh header on error statuses, the multipart body, and which calls are
retried.
"""

from __future__ import annotations

from datetime import date

import pytest
import requests
import responses

from bapp_connectors.core.dto import ImportStatus
from bapp_connectors.core.http import ResilientHttpClient, RetryPolicy
from bapp_connectors.core.types import BackoffStrategy
from bapp_connectors.providers.accounting.saga_web import SagaWebAdapter
from bapp_connectors.providers.accounting.saga_web.errors import SagaWebError

BASE = "https://web2.sagasoft.ro/sagac/api/v20260225/"
IMPORT_URL = BASE + "Import"
SOLD_URL = BASE + "Situatii/GetSoldCont"
KEY = "OLD-KEY-1"
NEW_KEY = "NEW-KEY-2"


def make_adapter(*, retry_policy=None, callback=None, token=KEY):
    http = ResilientHttpClient(base_url=BASE, provider_name="saga_web", retry_policy=retry_policy)
    adapter = SagaWebAdapter(
        credentials={"token": token, "cod_fiscal": "6716875", "base_url": BASE},
        http_client=http,
        on_credentials_update=callback,
    )
    return adapter


def no_wait_policy():
    return RetryPolicy(max_retries=2, backoff=BackoffStrategy.NONE)


@pytest.mark.parametrize("status", [207, 422, 502])
@responses.activate
def test_refresh_header_captured_on_error_statuses(status):
    responses.add(
        responses.POST,
        IMPORT_URL,
        body="Raport Import\nFactura 1.\nNR_DOC: 12\nEroare: client inexistent",
        status=status,
        headers={"X-Saga-Refresh-Token": NEW_KEY},
    )
    saved = []
    adapter = make_adapter(callback=saved.append)
    if status == 502:
        with pytest.raises(SagaWebError):
            adapter.import_file("F_1.xml", b"<Facturi/>")
    else:
        adapter.import_file("F_1.xml", b"<Facturi/>")
    assert saved == [{"token": NEW_KEY}]
    assert adapter.client.token == NEW_KEY
    assert responses.calls[0].request.headers["Authorization"] == f"Bearer {KEY}"


@responses.activate
def test_import_sends_multipart_file_and_import_automat():
    responses.add(responses.POST, IMPORT_URL, json={"success": True, "message": "Import realizat"}, status=200)
    result = make_adapter().import_file("F_1.xml", b"<Facturi><Factura/></Facturi>", auto_import=False)
    assert result.status == ImportStatus.OK
    request = responses.calls[0].request
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert request.headers["X-Saga-Cod-Fiscal"] == "6716875"
    body = request.body if isinstance(request.body, bytes) else request.body.encode()
    assert b'name="file"; filename="F_1.xml"' in body
    assert b"Content-Type: application/xml" in body
    assert b"<Facturi><Factura/></Facturi>" in body
    assert b'name="importAutomat"' in body
    assert b"false" in body


@responses.activate
def test_import_502_is_not_retried():
    responses.add(responses.POST, IMPORT_URL, body="<html>502 Bad Gateway</html>", status=502)
    adapter = make_adapter(retry_policy=no_wait_policy())
    with pytest.raises(SagaWebError) as exc_info:
        adapter.import_file("F_1.xml", b"<Facturi/>")
    assert len(responses.calls) == 1
    assert exc_info.value.retryable is False


@responses.activate
def test_import_connection_error_is_not_retried():
    responses.add(responses.POST, IMPORT_URL, body=requests.ConnectionError("reset"))
    adapter = make_adapter(retry_policy=no_wait_policy())
    with pytest.raises(SagaWebError) as exc_info:
        adapter.import_file("F_1.xml", b"<Facturi/>")
    assert len(responses.calls) == 1
    assert exc_info.value.retryable is False


@responses.activate
def test_read_503_is_retried_with_a_retry_policy():
    responses.add(responses.GET, SOLD_URL, body="<html>503</html>", status=503)
    responses.add(responses.GET, SOLD_URL, json={"success": True, "data": "12.5"}, status=200)
    adapter = make_adapter(retry_policy=no_wait_policy())
    assert str(adapter.get_account_balance("5121", "D", date(2026, 11, 3))) == "12.5"
    assert len(responses.calls) == 2


@responses.activate
def test_read_retry_sends_the_key_rotated_by_the_failed_attempt():
    responses.add(
        responses.GET, SOLD_URL, body="<html>503</html>", status=503, headers={"X-Saga-Refresh-Token": NEW_KEY}
    )
    responses.add(responses.GET, SOLD_URL, json={"success": True, "data": "1"}, status=200)
    saved = []
    adapter = make_adapter(retry_policy=no_wait_policy(), callback=saved.append)
    adapter.get_account_balance("5121", "D", date(2026, 11, 3))
    assert saved == [{"token": NEW_KEY}]
    assert responses.calls[0].request.headers["Authorization"] == f"Bearer {KEY}"
    assert responses.calls[1].request.headers["Authorization"] == f"Bearer {NEW_KEY}"


@responses.activate
def test_read_404_is_not_retried():
    responses.add(responses.GET, SOLD_URL, body="<html>404</html>", status=404)
    adapter = make_adapter(retry_policy=no_wait_policy())
    with pytest.raises(SagaWebError):
        adapter.get_account_balance("5121", "D", date(2026, 11, 3))
    assert len(responses.calls) == 1


@responses.activate
def test_newline_inside_the_key_never_reaches_the_message():
    responses.add(responses.GET, SOLD_URL, json={"success": True, "data": "1"}, status=200)
    adapter = make_adapter(token="SECRETKEY\nINJECTED")
    with pytest.raises(SagaWebError) as exc_info:
        adapter.get_account_balance("5121", "D", date(2026, 11, 3))
    assert str(exc_info.value) == "Credențiale SAGA Web invalide (ValueError)"
    assert "SECRETKEY" not in str(exc_info.value)
    assert len(responses.calls) == 0
    result = adapter.test_connection()
    assert result.success is False
    assert "SECRETKEY" not in result.message


@responses.activate
def test_trailing_newline_key_works():
    responses.add(responses.GET, SOLD_URL, json={"success": True, "data": "1"}, status=200)
    result = make_adapter(token=KEY + "\n").test_connection()
    assert result.success is True
    assert responses.calls[0].request.headers["Authorization"] == f"Bearer {KEY}"
