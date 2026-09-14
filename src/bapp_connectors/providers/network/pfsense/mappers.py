"""Map raw pfSense payloads to network DTOs."""

from __future__ import annotations

import ipaddress
import re

from bapp_connectors.core.dto import NetworkClient, NetworkDeviceInfo, NetworkSegment
from bapp_connectors.core.dto.base import ProviderMeta
from bapp_connectors.providers.network.pfsense.models import RawArpEntry, RawDeviceInfo, RawInterface, RawLease

PROVIDER = "pfsense"
_ARP_RE = re.compile(r"^\S+ \((?P<ip>[0-9.]+)\) at (?P<mac>[0-9a-f:]{17}) on (?P<iface>\S+) (?P<state>.+?) \[")
_INFO_KEYS = ("hostname", "version", "platform", "uptime")


def _meta(raw_id: str = "") -> ProviderMeta:
    return ProviderMeta(provider=PROVIDER, raw_id=raw_id)


def parse_arp(text: str) -> list[RawArpEntry]:
    entries: list[RawArpEntry] = []
    for line in text.splitlines():
        m = _ARP_RE.match(line.strip())
        if not m:
            continue  # "(incomplete)" has no MAC and does not match
        state = m.group("state")
        if state.startswith(("permanent", "expired")):
            continue
        entries.append(RawArpEntry(ip=m.group("ip"), mac=m.group("mac"), iface=m.group("iface")))
    return entries


def map_device_info(payload: dict) -> NetworkDeviceInfo:
    raw = RawDeviceInfo(**{k: v for k, v in payload.items() if k in RawDeviceInfo.model_fields})
    extra = {k: v for k, v in payload.items() if k not in _INFO_KEYS}
    return NetworkDeviceInfo(
        hostname=raw.hostname,
        model=raw.platform,
        version=raw.version,
        uptime_seconds=raw.uptime,
        extra=extra,
        provider_meta=_meta(raw.hostname),
    )


def _cidr(ip: str, subnet: str | int | None) -> str:
    if not ip or subnet in (None, ""):
        return ""
    try:
        return str(ipaddress.ip_network(f"{ip}/{int(subnet)}", strict=False))
    except ValueError:
        return ""


def map_segments(payload: list[dict]) -> list[NetworkSegment]:
    segments: list[NetworkSegment] = []
    for item in payload:
        raw = RawInterface(**item)
        if not raw.ip:
            continue
        has_range = raw.dhcp_enabled and raw.dhcp_from and raw.dhcp_to
        segments.append(
            NetworkSegment(
                ref=raw.ref,
                name=raw.descr or raw.ref,
                cidr=_cidr(raw.ip, raw.subnet),
                gateway_ip=raw.ip,
                dhcp_range=f"{raw.dhcp_from}-{raw.dhcp_to}" if has_range else "",
                extra={"dhcp_enabled": raw.dhcp_enabled},
                provider_meta=_meta(raw.ref),
            )
        )
    return segments


def _in_cidr(ip: str, cidr: str | None) -> bool:
    if not cidr:
        return True
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def map_clients(leases: list[dict], arp_text: str, cidr: str | None) -> list[NetworkClient]:
    arp_by_ip = {e.ip: e for e in parse_arp(arp_text)}
    clients: dict[str, NetworkClient] = {}
    for item in leases:
        raw = RawLease(**{k: v for k, v in item.items() if k in RawLease.model_fields})
        if not _in_cidr(raw.ip, cidr):
            continue
        in_arp = raw.ip in arp_by_ip
        clients[raw.ip] = NetworkClient(
            ip=raw.ip,
            mac=(raw.mac or (arp_by_ip[raw.ip].mac if in_arp else "")).lower(),
            hostname=raw.hostname,
            online=in_arp or raw.online.startswith("active"),
            lease_starts=raw.starts,
            lease_ends=raw.ends,
            extra={"source": "dhcp", "lease_state": raw.act, "lease_type": raw.type},
            provider_meta=_meta(raw.mac),
        )
    for ip, entry in arp_by_ip.items():
        if ip in clients or not _in_cidr(ip, cidr):
            continue
        clients[ip] = NetworkClient(
            ip=ip,
            mac=entry.mac.lower(),
            online=True,
            extra={"source": "arp", "iface": entry.iface},
            provider_meta=_meta(entry.mac),
        )
    return sorted(clients.values(), key=lambda c: ipaddress.ip_address(c.ip))


def segment_ref_for(ip: str, segments: list[NetworkSegment]) -> str:
    for seg in segments:
        if seg.cidr and _in_cidr(ip, seg.cidr):
            return seg.ref
    return ""
