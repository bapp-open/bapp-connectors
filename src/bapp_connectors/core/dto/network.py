"""Network family DTOs — routers, segments, connected clients, DNS allowlists."""

from __future__ import annotations

from bapp_connectors.core.dto.base import BaseDTO


class NetworkDeviceInfo(BaseDTO):
    """Identity of the managed network device (router/firewall)."""

    hostname: str
    model: str = ""
    version: str = ""
    uptime_seconds: int | None = None
    extra: dict = {}


class NetworkSegment(BaseDTO):
    """A network segment (interface/VLAN) with an address on the device."""

    ref: str
    name: str = ""
    cidr: str = ""
    gateway_ip: str = ""
    dhcp_range: str = ""
    extra: dict = {}


class NetworkClient(BaseDTO):
    """A client seen on the network (DHCP lease and/or ARP entry)."""

    ip: str
    mac: str = ""
    hostname: str = ""
    online: bool = False
    segment_ref: str = ""
    lease_starts: str = ""
    lease_ends: str = ""
    extra: dict = {}


class DnsAllowlist(BaseDTO):
    """The DNS allowlist applied to a segment.

    `present` is False when the device has no allowlist configured for the segment.
    `raw` is the provider-specific text block that encodes the list.
    `backup` is a provider-specific snapshot of the configuration taken before a write.
    """

    segment_ref: str
    domains: list[str] = []
    present: bool = True
    raw: str = ""
    backup: str = ""


class DetectedDnsAllowlist(BaseDTO):
    """An allowlist found on the device, mapped to a segment, with its provider config."""

    segment_ref: str
    config: dict = {}
    domains: list[str] = []
    raw: str = ""
