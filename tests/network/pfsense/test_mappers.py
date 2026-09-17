"""Mapper tests for the pfSense provider."""

from bapp_connectors.core.dto import NetworkClient, NetworkDeviceInfo, NetworkSegment
from bapp_connectors.providers.network.pfsense.mappers import (
    map_clients,
    map_device_info,
    map_segments,
    parse_arp,
    segment_ref_for,
)

ARP = """? (5.2.251.1) at (incomplete) on igc2 expired [ethernet]
? (5.2.251.35) at 90:ec:77:98:3b:7f on igc2 permanent [ethernet]
? (192.168.1.34) at 9c:93:4e:8f:e1:ce on igc3 expires in 1033 seconds [ethernet]
? (10.10.197.13) at f8:e4:3b:34:ba:0b on bridge0 expires in 296 seconds [bridge]
? (172.16.199.10) at b2:a1:c7:20:19:f2 on igc0.20 expires in 100 seconds [vlan]
"""

LEASES = [
    {"act": "active", "type": "dynamic", "ip": "10.10.197.13", "mac": "f8:e4:3b:34:ba:0b",
     "online": "active/online", "hostname": "alienware", "starts": "2026/09/14 08:21:53", "ends": "2026/09/14 10:21:53"},
    {"act": "active", "type": "dynamic", "ip": "172.16.199.10", "mac": "b2:a1:c7:20:19:f2",
     "online": "idle/offline", "hostname": "fold7", "starts": "2026/09/14 07:41:46", "ends": "2026/09/14 09:41:46"},
    {"act": "expired", "type": "dynamic", "ip": "172.16.199.11", "mac": "aa:aa:aa:aa:aa:aa",
     "online": "idle/offline", "hostname": "", "starts": "", "ends": ""},
]

INTERFACES = [
    {"ref": "lan", "descr": "LAN", "ip": "10.10.198.1", "subnet": "22", "dhcp_from": "10.10.197.10", "dhcp_to": "10.10.197.250", "dhcp_enabled": True},
    {"ref": "opt3", "descr": "ELEVI", "ip": "172.16.198.1", "subnet": 22, "dhcp_from": "", "dhcp_to": "", "dhcp_enabled": False},
    {"ref": "wan", "descr": "WAN_ORANGE", "ip": "192.168.1.69", "subnet": 24, "dhcp_from": "", "dhcp_to": "", "dhcp_enabled": False},
]


def test_parse_arp_skips_incomplete_permanent_and_expired():
    entries = parse_arp(ARP)
    assert [(e.ip, e.mac, e.iface) for e in entries] == [
        ("192.168.1.34", "9c:93:4e:8f:e1:ce", "igc3"),
        ("10.10.197.13", "f8:e4:3b:34:ba:0b", "bridge0"),
        ("172.16.199.10", "b2:a1:c7:20:19:f2", "igc0.20"),
    ]


def test_map_segments_computes_cidr_and_dhcp_range():
    segs = map_segments(INTERFACES)
    assert isinstance(segs[0], NetworkSegment)
    lan = next(s for s in segs if s.ref == "lan")
    assert lan.name == "LAN" and lan.cidr == "10.10.196.0/22" and lan.gateway_ip == "10.10.198.1"
    assert lan.dhcp_range == "10.10.197.10-10.10.197.250"
    opt3 = next(s for s in segs if s.ref == "opt3")
    assert opt3.cidr == "172.16.196.0/22" and opt3.dhcp_range == ""
    assert segs[0].provider_meta.provider == "pfsense"


def test_map_device_info():
    info = map_device_info({"hostname": "RM-FW-01", "domain": "reginamaria.local", "version": "26.07-RELEASE", "uptime": 5756, "platform": "Netgate 4100"})
    assert isinstance(info, NetworkDeviceInfo)
    assert info.hostname == "RM-FW-01" and info.version == "26.07-RELEASE" and info.model == "Netgate 4100"
    assert info.uptime_seconds == 5756 and info.extra["domain"] == "reginamaria.local"


def test_map_clients_merges_leases_and_arp_and_filters_by_cidr():
    clients = map_clients(LEASES, ARP, cidr=None)
    by_ip = {c.ip: c for c in clients}
    assert isinstance(by_ip["10.10.197.13"], NetworkClient)
    assert by_ip["10.10.197.13"].online is True and by_ip["10.10.197.13"].hostname == "alienware"
    # lease says idle/offline but ARP still has it: online wins
    assert by_ip["172.16.199.10"].online is True
    # ARP-only host (static IP) shows up without hostname
    assert by_ip["192.168.1.34"].hostname == "" and by_ip["192.168.1.34"].online is True
    assert by_ip["192.168.1.34"].extra["source"] == "arp"
    # expired lease, not in ARP
    assert by_ip["172.16.199.11"].online is False and by_ip["172.16.199.11"].extra["lease_state"] == "expired"

    only_elevi = map_clients(LEASES, ARP, cidr="172.16.196.0/22")
    assert sorted(c.ip for c in only_elevi) == ["172.16.199.10", "172.16.199.11"]


def test_null_fields_from_php_fall_back_to_defaults():
    """pfSense trimite `null` pentru valorile absente (lease static fără `cid`, interfață fără range DHCP)."""
    leases = [
        {"act": "active", "type": "static", "ip": "172.16.199.50", "mac": "aa:bb:cc:dd:ee:ff",
         "cid": None, "hostname": None, "online": None, "starts": None, "ends": None},
    ]
    clients = map_clients(leases, "", cidr=None)
    assert len(clients) == 1
    assert clients[0].ip == "172.16.199.50"
    assert clients[0].hostname == "" and clients[0].lease_ends == "" and clients[0].online is False
    assert clients[0].extra["lease_type"] == "static"

    segments = map_segments([
        {"ref": "opt3", "descr": None, "ip": "172.16.198.1", "subnet": 22,
         "dhcp_from": None, "dhcp_to": None, "dhcp_enabled": None},
    ])
    assert segments[0].name == "opt3"  # fără descriere, cade pe ref
    assert segments[0].dhcp_range == "" and segments[0].cidr == "172.16.196.0/22"

    info = map_device_info({"hostname": "RM-FW-01", "version": None, "platform": None, "uptime": None})
    assert info.hostname == "RM-FW-01" and info.version == "" and info.model == ""
    assert info.uptime_seconds is None


def test_segment_ref_for():
    segs = map_segments(INTERFACES)
    assert segment_ref_for("10.10.197.13", segs) == "lan"
    assert segment_ref_for("172.16.199.10", segs) == "opt3"
    assert segment_ref_for("8.8.8.8", segs) == ""
