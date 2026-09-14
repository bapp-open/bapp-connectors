"""Adapter tests with a fake HTTP client returning canned XML-RPC payloads."""

import json

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, NetworkClient, NetworkDeviceInfo, NetworkSegment
from bapp_connectors.core.errors import AuthenticationError, ConfigurationError
from bapp_connectors.providers.network.pfsense.adapter import PfSenseNetworkAdapter
from tests.fake_http import FakeHttpClient
from tests.network.pfsense.test_client import xmlrpc_string
from tests.network.pfsense.test_mappers import ARP, INTERFACES, LEASES

ENDPOINT = "https://fw.example:8885"
DEVICE = {"hostname": "RM-FW-01", "domain": "reginamaria.local", "version": "26.07-RELEASE", "platform": "Netgate 4100", "uptime": 10}


class Router:
    """Routes exec_php calls to canned JSON by looking at a marker in the PHP body."""

    def __init__(self):
        self.responses: dict[str, object] = {}
        self.seen: list[str] = []

    def when(self, marker: str, payload):
        self.responses[marker] = payload
        return self

    def __call__(self, method, path, kwargs):
        body = kwargs["data"].decode()
        self.seen.append(body)
        for marker, payload in self.responses.items():
            if marker in body:
                return xmlrpc_string(json.dumps(payload() if callable(payload) else payload))
        raise AssertionError(f"no canned response for PHP body:\n{body}")


def make_adapter(router: Router, endpoints: str | list = ENDPOINT, **config):
    fake = FakeHttpClient()
    fake.add("POST", "xmlrpc.php", router)
    return PfSenseNetworkAdapter(
        credentials={"username": "admin", "password": "secret"},
        http_client=fake,
        config={"endpoints": endpoints, "verify_ssl": False, **config},
    )


def test_endpoints_accepts_multiline_string_and_list():
    assert PfSenseNetworkAdapter._endpoints({"endpoints": "https://a:8885\n\n https://b:8885/ \n"}) == ["https://a:8885", "https://b:8885"]
    assert PfSenseNetworkAdapter._endpoints({"endpoints": ["https://a:8885"]}) == ["https://a:8885"]
    assert PfSenseNetworkAdapter._endpoints({}) == []


def test_validate_credentials():
    adapter = make_adapter(Router())
    assert adapter.validate_credentials() is True
    bad = PfSenseNetworkAdapter(credentials={"username": "admin"}, http_client=FakeHttpClient(), config={"endpoints": ENDPOINT})
    assert bad.validate_credentials() is False


def test_test_connection_success_and_failure():
    adapter = make_adapter(Router().when("bapp:device_info", DEVICE))
    result = adapter.test_connection()
    assert isinstance(result, ConnectionTestResult)
    assert result.success is True and "RM-FW-01" in result.message
    assert result.details["version"] == "26.07-RELEASE"

    def boom(method, path, kwargs):
        raise AuthenticationError("401 Unauthorized")

    fake = FakeHttpClient()
    fake.add("POST", "xmlrpc.php", boom)
    failing = PfSenseNetworkAdapter(credentials={"username": "a", "password": "b"}, http_client=fake, config={"endpoints": ENDPOINT})
    result = failing.test_connection()
    assert result.success is False and "401" in result.message


def test_get_device_info_and_segments():
    router = Router().when("bapp:device_info", DEVICE).when("bapp:segments", INTERFACES)
    adapter = make_adapter(router)
    info = adapter.get_device_info()
    assert isinstance(info, NetworkDeviceInfo) and info.hostname == "RM-FW-01"
    segs = adapter.list_segments()
    assert [s.ref for s in segs] == ["lan", "opt3", "wan"]
    assert all(isinstance(s, NetworkSegment) for s in segs)


def test_list_clients_all_and_per_segment():
    router = (
        Router()
        .when("bapp:segments", INTERFACES)
        .when("bapp:clients", {"leases": LEASES, "arp": ARP})
    )
    adapter = make_adapter(router)
    everyone = adapter.list_clients()
    assert all(isinstance(c, NetworkClient) for c in everyone)
    assert {c.ip: c.segment_ref for c in everyone}["10.10.197.13"] == "lan"
    elevi = adapter.list_clients("opt3")
    assert sorted(c.ip for c in elevi) == ["172.16.199.10", "172.16.199.11"]
    assert all(c.segment_ref == "opt3" for c in elevi)


def test_unknown_segment_raises():
    adapter = make_adapter(Router().when("bapp:segments", INTERFACES))
    with pytest.raises(ConfigurationError):
        adapter.list_clients("opt9")


def test_registry_builds_adapter_with_config_defaults():
    import bapp_connectors.providers.network.pfsense  # noqa: F401
    from bapp_connectors.core.registry import registry

    adapter = registry.create_adapter(
        "network", "pfsense",
        credentials={"username": "admin", "password": "x"},
        config={"endpoints": "https://fw.example:8885"},
    )
    assert isinstance(adapter, PfSenseNetworkAdapter)
    assert adapter.client.endpoints == ["https://fw.example:8885"]
    assert adapter.client.verify_ssl is False and adapter.client.timeout == 20
    assert adapter.client.http._session.verify is False
