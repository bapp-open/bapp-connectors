"""Family-level tests: enum, DTOs, port and capability shapes."""

from abc import ABC

import pytest
from pydantic import ValidationError

from bapp_connectors.core.capabilities import DnsAllowlistCapability
from bapp_connectors.core.dto import DnsAllowlist, NetworkClient, NetworkDeviceInfo, NetworkSegment
from bapp_connectors.core.ports import BasePort, NetworkPort
from bapp_connectors.core.types import ProviderFamily


def test_network_family_enum():
    assert ProviderFamily.NETWORK == "network"
    assert ProviderFamily("network") is ProviderFamily.NETWORK


def test_dtos_are_frozen_with_defaults():
    seg = NetworkSegment(ref="opt3")
    assert seg.name == "" and seg.cidr == "" and seg.extra == {}
    with pytest.raises(ValidationError):
        seg.name = "x"  # frozen
    client = NetworkClient(ip="172.16.199.10")
    assert client.online is False and client.mac == ""
    info = NetworkDeviceInfo(hostname="fw")
    assert info.uptime_seconds is None
    allow = DnsAllowlist(segment_ref="opt3")
    assert allow.domains == [] and allow.present is True and allow.raw == "" and allow.backup == ""


def test_port_and_capability_are_abstract():
    assert issubclass(NetworkPort, BasePort)
    assert issubclass(DnsAllowlistCapability, ABC)
    assert not issubclass(DnsAllowlistCapability, BasePort)
    with pytest.raises(TypeError):
        NetworkPort()  # type: ignore[abstract]
    abstract = NetworkPort.__abstractmethods__
    assert {"get_device_info", "list_segments", "list_clients", "validate_credentials", "test_connection"} <= abstract
    assert {"get_dns_allowlist", "set_dns_allowlist"} == set(DnsAllowlistCapability.__abstractmethods__)
    assert DnsAllowlistCapability.detect_dns_allowlists(object()) == []
