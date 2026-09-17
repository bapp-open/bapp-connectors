"""Family-level tests: enum, DTOs, port shape."""

from abc import ABC

import pytest
from pydantic import ValidationError

from bapp_connectors.core.dto import DnsRecord, DnsZone, DnsZoneSnapshot
from bapp_connectors.core.ports import BasePort, DnsPort
from bapp_connectors.core.types import ProviderFamily


def test_dns_family_enum():
    assert ProviderFamily.DNS == "dns"
    assert ProviderFamily("dns") is ProviderFamily.DNS


def test_dtos_are_frozen_with_defaults():
    zone = DnsZone(zone="example.test")
    assert zone.editable is True and zone.extra == {}
    with pytest.raises(ValidationError):
        zone.zone = "x"  # frozen

    rec = DnsRecord(name="example.test.", record_type="A", ttl=14400, value="192.0.2.10")
    assert rec.ref == "", "ref is empty for a record that does not exist yet"
    assert rec.priority is None and rec.extra == {}

    snap = DnsZoneSnapshot(zone="example.test", version="2026010101")
    assert snap.records == []


def test_port_is_abstract_and_declares_supported_types():
    assert issubclass(DnsPort, BasePort)
    assert issubclass(DnsPort, ABC)
    with pytest.raises(TypeError):
        DnsPort()  # type: ignore[abstract]
    assert {
        "list_zones",
        "get_zone",
        "apply_changes",
        "validate_credentials",
        "test_connection",
    } <= DnsPort.__abstractmethods__
    assert DnsPort.supported_record_types == ()
