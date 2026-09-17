"""Reusable contract tests every DNS provider must pass.

A provider satisfies this whether DNS is its whole purpose (Cloudflare) or one
capability among many (cPanel).
"""

import pytest

from bapp_connectors.core.dto import DnsRecord, DnsZone, DnsZoneSnapshot
from bapp_connectors.core.ports import DnsPort


class DnsContractTests:
    @pytest.fixture
    def dns_adapter(self) -> DnsPort:
        raise NotImplementedError("provider tests must supply a dns_adapter fixture")

    @pytest.fixture
    def zone_name(self) -> str:
        raise NotImplementedError("provider tests must supply a zone_name fixture")

    def test_is_dns_port(self, dns_adapter):
        assert isinstance(dns_adapter, DnsPort)

    def test_declares_writable_record_types(self, dns_adapter):
        types = dns_adapter.supported_record_types
        assert isinstance(types, tuple) and types, "a writable provider names its record types"
        assert "A" in types

    def test_list_zones(self, dns_adapter):
        zones = dns_adapter.list_zones()
        assert isinstance(zones, list)
        assert all(isinstance(z, DnsZone) and z.zone for z in zones)

    def test_get_zone_returns_a_snapshot(self, dns_adapter, zone_name):
        snapshot = dns_adapter.get_zone(zone_name)
        assert isinstance(snapshot, DnsZoneSnapshot)
        assert snapshot.zone == zone_name
        assert all(isinstance(r, DnsRecord) for r in snapshot.records)
        assert all(r.ref for r in snapshot.records), "a read record always has a ref"
