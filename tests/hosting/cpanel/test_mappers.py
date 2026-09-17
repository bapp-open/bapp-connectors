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
