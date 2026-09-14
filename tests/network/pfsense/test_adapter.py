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


# -- DnsAllowlistCapability ------------------------------------------------------------

import base64  # noqa: E402
import re  # noqa: E402

from bapp_connectors.core.capabilities import DnsAllowlistCapability  # noqa: E402
from bapp_connectors.core.dto import DnsAllowlist  # noqa: E402
from bapp_connectors.providers.network.pfsense.unbound import parse_view, render_view  # noqa: E402

LEGACY_OPTIONS = (
    "server:\n"
    "access-control-view: 172.16.196.0/22 elevi\n"
    "view:\n"
    'name: "elevi"\n'
    "view-first: yes\n"
    'local-zone: "." always_nxdomain\n'
    'local-zone: "google.com." transparent\n'
    'local-zone: "whatsapp.com." transparent\n'
)


class UnboundState:
    """Fake pfSense config state for the unbound section, shared between canned responses."""

    def __init__(self, custom_options: str):
        self.custom_options = custom_options
        self.writes: list[dict] = []
        self.hot_apply: list[str] = []

    def get(self):
        return {
            "custom_options": base64.b64encode(self.custom_options.encode()).decode() if self.custom_options else "",
            "section": {"enable": "", "custom_options": "..."},
        }

    def set(self, body: str):
        m = re.search(r"base64_decode\('([^']+)'\)", body)
        self.custom_options = base64.b64decode(m.group(1)).decode()
        self.writes.append({"body": body})
        return True

    def apply(self, body: str):
        m = re.search(r"base64_decode\('([^']+)'\)", body)
        self.hot_apply.append(base64.b64decode(m.group(1)).decode())
        return {"ok": True, "output": ""}


def make_dns_adapter(state: UnboundState):
    router = Router().when("bapp:segments", INTERFACES)
    router.responses["bapp:get_unbound"] = state.get
    fake = FakeHttpClient()

    def dispatch(method, path, kwargs):
        body = kwargs["data"].decode()
        if "bapp:set_unbound" in body:
            return xmlrpc_string(json.dumps(state.set(body)))
        if "bapp:hot_apply" in body:
            return xmlrpc_string(json.dumps(state.apply(body)))
        return router(method, path, kwargs)

    fake.add("POST", "xmlrpc.php", dispatch)
    adapter = PfSenseNetworkAdapter(
        credentials={"username": "admin", "password": "secret"},
        http_client=fake,
        config={"endpoints": ENDPOINT},
    )
    return adapter, state


def test_adapter_declares_capability():
    assert isinstance(make_adapter(Router()), DnsAllowlistCapability)
    assert DnsAllowlistCapability in PfSenseNetworkAdapter.manifest.capabilities


def test_get_dns_allowlist_reads_legacy_block():
    adapter, _ = make_dns_adapter(UnboundState(LEGACY_OPTIONS))
    result = adapter.get_dns_allowlist("opt3", {"view": "elevi"})
    assert isinstance(result, DnsAllowlist)
    assert result.present is True
    assert result.domains == ["google.com", "whatsapp.com"]
    assert result.segment_ref == "opt3"
    assert result.raw.startswith("view:")


def test_get_dns_allowlist_absent_view():
    adapter, _ = make_dns_adapter(UnboundState("server:\nlog-queries: no\n"))
    result = adapter.get_dns_allowlist("opt3", {"view": "elevi"})
    assert result.present is False and result.domains == [] and result.raw == ""


def test_get_dns_allowlist_requires_view():
    adapter, _ = make_dns_adapter(UnboundState(""))
    with pytest.raises(ConfigurationError):
        adapter.get_dns_allowlist("opt3", {})


def test_set_dns_allowlist_adopts_legacy_and_hot_applies_diff():
    adapter, state = make_dns_adapter(UnboundState("server:\nlog-queries: no\n" + LEGACY_OPTIONS))
    result = adapter.set_dns_allowlist("opt3", {"view": "elevi"}, ["google.com", "youtube.com"])

    # persisted text: untouched prefix, block adopted with markers, CIDR taken from the segment
    assert state.custom_options.startswith("server:\nlog-queries: no\nserver:\n")
    parsed = parse_view(state.custom_options, "elevi")
    assert parsed.managed is True and parsed.cidr == "172.16.196.0/22"
    assert parsed.domains == ["google.com", "youtube.com"]
    assert state.custom_options.count("access-control-view:") == 1

    # write_config + unbound reconfigure happened once
    assert len(state.writes) == 1
    assert "write_config(" in state.writes[0]["body"] and "services_unbound_configure(" in state.writes[0]["body"]

    # hot apply: youtube added, whatsapp removed
    assert len(state.hot_apply) == 1
    assert "view_local_zone elevi youtube.com. transparent" in state.hot_apply[0]
    assert "view_local_zone_remove elevi whatsapp.com." in state.hot_apply[0]
    assert "google.com" not in state.hot_apply[0]

    # returned value is the re-read list, with the backup attached
    assert result.domains == ["google.com", "youtube.com"] and result.present is True
    assert json.loads(result.backup)["enable"] == ""


def test_set_dns_allowlist_explicit_cidr_and_empty_list():
    adapter, state = make_dns_adapter(UnboundState(""))
    result = adapter.set_dns_allowlist("opt3", {"view": "elevi", "cidr": "172.16.199.0/24"}, [])
    assert state.custom_options == render_view("elevi", "172.16.199.0/24", [])
    assert result.domains == [] and result.present is True
    assert state.hot_apply == []  # nothing to add or remove
