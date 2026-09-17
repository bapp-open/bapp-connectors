"""Mapper tests. Every case here is one that fails silently if mapped wrong."""

from datetime import UTC
from decimal import Decimal

from bapp_connectors.providers.hosting.cpanel.mappers import map_account, map_domains, map_usages


def test_byte_formatted_resources_carry_the_bytes_unit(usages_raw):
    by_key = {r.key: r for r in map_usages(usages_raw)}
    disk = by_key["disk_usage"]
    assert disk.unit == "bytes"
    assert disk.used == Decimal("1305116672")
    assert disk.limit == Decimal("128849018880")
    assert by_key["email_accounts"].unit == "count"


def test_null_maximum_means_unlimited_not_zero(usages_raw):
    by_key = {r.key: r for r in map_usages(usages_raw)}
    # `forwarders` and `autoresponders` really do come back with maximum: null.
    assert by_key["forwarders"].limit is None
    assert by_key["autoresponders"].limit is None


def test_percent_is_computed_only_when_a_limit_exists(usages_raw):
    by_key = {r.key: r for r in map_usages(usages_raw)}
    assert by_key["forwarders"].percent is None
    assert by_key["disk_usage"].percent is not None
    assert 0 <= by_key["disk_usage"].percent <= 100


def test_main_domain_is_mapped_with_its_kind(domains_raw):
    domains = map_domains(domains_raw, [])
    assert len(domains) == 1
    main = domains[0]
    assert main.domain == "example.test"
    assert main.kind == "main"
    assert main.document_root == "/home/exampleuser/public_html"
    assert main.ssl_expires_at is None, "no certs passed in"


def test_ssl_is_merged_onto_the_matching_domain(domains_raw, ssl_raw):
    main = map_domains(domains_raw, ssl_raw)[0]
    assert main.ssl_expires_at is not None
    assert main.ssl_expires_at.tzinfo is not None, "not_after is a unix int; make it aware"
    assert main.ssl_expires_at.tzinfo is UTC
    assert main.ssl_auto is True
    assert main.ssl_issuer


def test_account_takes_the_hostname_from_the_connection():
    info = {"user": "exampleuser", "maximum_mail_accounts": 1000, "plan": "starter"}
    acc = map_account(info, hostname="cpanel.example.net", primary_domain="example.test")
    assert acc.username == "exampleuser"
    assert acc.primary_domain == "example.test"
    assert acc.server_hostname == "cpanel.example.net"
    assert acc.plan == "starter"


from bapp_connectors.core.dto import DnsRecord  # noqa: E402
from bapp_connectors.providers.hosting.cpanel.mappers import (  # noqa: E402
    map_mailboxes,
    map_zone,
    record_to_payload,
)


def test_mailbox_quota_comes_from_the_byte_pair_not_the_megabyte_pair(pops_raw):
    # diskquota is "1024.00" MB while _diskquota is "1073741824" bytes. Reading the
    # wrong one is a factor-1048576 error that still looks plausible in a UI.
    boxes = {b.email: b for b in map_mailboxes(pops_raw)}
    admin = boxes["admin@example.test"]
    assert admin.disk_quota == Decimal("1073741824")
    assert admin.disk_used == Decimal("903985792")
    assert admin.percent_used is not None and admin.percent_used > 80


def test_mailbox_suspension_flags_become_booleans(pops_raw):
    box = map_mailboxes(pops_raw)[0]
    assert box.suspended_login is False
    assert box.suspended_incoming is False


def test_zone_skips_comments_and_controls_and_keeps_the_serial(zone_raw):
    snapshot = map_zone("example.test", zone_raw)
    assert snapshot.zone == "example.test"
    assert snapshot.version, "the SOA serial is the write token"
    assert all(r.record_type not in ("", None) for r in snapshot.records)
    assert not any(r.record_type == "SOA" for r in snapshot.records), "SOA is not an editable record"


def test_records_are_decoded_and_carry_their_line_index_as_ref(zone_raw):
    records = map_zone("example.test", zone_raw).records
    a_record = next(r for r in records if r.record_type == "A")
    assert a_record.name == "example.test."
    assert a_record.value == "192.0.2.10"
    assert a_record.ref.isdigit(), "cPanel's ref is the line index"
    assert a_record.ttl == 14400


def test_mx_lifts_its_priority_out_of_the_positional_array(zone_raw):
    mx = next(r for r in map_zone("example.test", zone_raw).records if r.record_type == "MX")
    assert mx.priority == 0
    assert mx.value == "example.test."


def test_srv_keeps_weight_and_port_in_extra(zone_raw):
    srv = next(r for r in map_zone("example.test", zone_raw).records if r.record_type == "SRV")
    assert srv.priority == 0
    assert srv.extra["weight"] == 0
    assert srv.extra["port"] == 2080
    assert srv.value == "example.test."


def test_payload_data_is_always_an_array():
    # The server rejects a scalar: '"data" must be an array.'
    payload = record_to_payload(DnsRecord(name="www", record_type="A", ttl=300, value="192.0.2.11"))
    assert payload == {"dname": "www", "ttl": 300, "record_type": "A", "data": ["192.0.2.11"]}


def test_payload_rebuilds_mx_positionally():
    payload = record_to_payload(
        DnsRecord(name="example.test.", record_type="MX", ttl=300, value="mail.example.test.", priority=10)
    )
    assert payload["data"] == ["10", "mail.example.test."]


def test_payload_for_an_edit_carries_the_line_index():
    payload = record_to_payload(
        DnsRecord(ref="13", name="www", record_type="A", ttl=300, value="192.0.2.11"), include_ref=True
    )
    assert payload["line_index"] == 13
