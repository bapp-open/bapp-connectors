"""PfSenseClient: XML-RPC encoding/decoding and endpoint failover."""

import json

import pytest

from bapp_connectors.core.errors import AuthenticationError, ConfigurationError, ProviderError
from bapp_connectors.providers.network.pfsense.client import (
    PfSenseClient,
    build_exec_php_body,
    parse_response,
)
from bapp_connectors.providers.network.pfsense.errors import PfSenseFaultError, PfSenseUnreachableError
from tests.fake_http import FakeHttpClient


def xmlrpc_string(value: str) -> str:
    from xml.sax.saxutils import escape

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<methodResponse><params><param><value><string>"
        f"{escape(value)}"
        "</string></value></param></params></methodResponse>"
    )


FAULT = (
    '<?xml version="1.0"?><methodResponse><fault><value><struct>'
    "<member><name>faultCode</name><value><int>4</int></value></member>"
    "<member><name>faultString</name><value><string>Too many parameters.</string></value></member>"
    "</struct></value></fault></methodResponse>"
)


def test_build_body_wraps_code_in_cdata_and_escapes_terminator():
    body = build_exec_php_body('echo "]]>";')
    assert body.startswith('<?xml version="1.0"?>')
    assert "<methodName>pfsense.exec_php</methodName>" in body
    assert "<![CDATA[" in body
    assert 'echo "]]]]><![CDATA[>";' in body


def test_parse_response_returns_value_and_raises_on_fault():
    assert parse_response(xmlrpc_string("RM-FW-01")) == "RM-FW-01"
    with pytest.raises(PfSenseFaultError) as exc:
        parse_response(FAULT)
    assert exc.value.fault_code == 4
    assert "Too many parameters" in str(exc.value)


def test_run_decodes_json_and_targets_first_endpoint():
    fake = FakeHttpClient()
    fake.add("POST", "https://a.example:8885/xmlrpc.php", xmlrpc_string(json.dumps({"hostname": "fw"})))
    client = PfSenseClient(fake, endpoints=["https://a.example:8885", "https://b.example:8885"], verify_ssl=False)
    assert client.run('return ["hostname" => "fw"];') == {"hostname": "fw"}
    call = fake.last_call()
    assert call.method == "POST"
    assert call.path == "https://a.example:8885/xmlrpc.php"
    assert call.kwargs["headers"]["Content-Type"] == "text/xml"
    assert call.kwargs["verify"] is False
    assert call.kwargs["retry"] is False
    assert b"global $toreturn;" in call.kwargs["data"]
    assert b'return ["hostname" => "fw"];' in call.kwargs["data"]
    assert client.active_endpoint == "https://a.example:8885"


def test_failover_to_second_endpoint_on_transport_error():
    fake = FakeHttpClient()

    def boom(method, path, kwargs):
        raise ProviderError("connection refused", status_code=None)

    fake.add("POST", "https://a.example:8885/xmlrpc.php", boom)
    fake.add("POST", "https://b.example:8885/xmlrpc.php", xmlrpc_string(json.dumps(1)))
    client = PfSenseClient(fake, endpoints=["https://a.example:8885/", "https://b.example:8885"])
    assert client.run("return 1;") == 1
    assert client.active_endpoint == "https://b.example:8885"
    # the working endpoint is tried first from now on
    assert client.run("return 1;") == 1
    assert fake.last_call().path == "https://b.example:8885/xmlrpc.php"


def test_all_endpoints_down_raises_unreachable():
    fake = FakeHttpClient()

    def boom(method, path, kwargs):
        raise ProviderError("timeout")

    fake.add("POST", "xmlrpc.php", boom)
    client = PfSenseClient(fake, endpoints=["https://a.example:8885", "https://b.example:8885"])
    with pytest.raises(PfSenseUnreachableError) as exc:
        client.run("return 1;")
    assert exc.value.retryable is True
    assert exc.value.attempts == ["https://a.example:8885", "https://b.example:8885"]
    assert "a.example" in str(exc.value) and "b.example" in str(exc.value)


def test_auth_error_is_not_retried_on_other_endpoints():
    fake = FakeHttpClient()
    calls = []

    def unauthorized(method, path, kwargs):
        calls.append(path)
        raise AuthenticationError("401")

    fake.add("POST", "xmlrpc.php", unauthorized)
    client = PfSenseClient(fake, endpoints=["https://a.example:8885", "https://b.example:8885"])
    with pytest.raises(AuthenticationError):
        client.run("return 1;")
    assert calls == ["https://a.example:8885/xmlrpc.php"]


def test_requires_at_least_one_endpoint():
    with pytest.raises(ConfigurationError):
        PfSenseClient(FakeHttpClient(), endpoints=[])
