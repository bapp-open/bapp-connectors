"""Live cPanel tests. Read-only unless CPANEL_ALLOW_WRITES=1.

The account these run against is a live production account. Writes are gated
separately and are meant for a disposable account, never a real one.
"""

import os

import pytest

from bapp_connectors.core.dto import HostingAccount
from bapp_connectors.providers.hosting.cpanel import CpanelAdapter

CREDENTIALS = {
    "hostname": os.getenv("CPANEL_HOSTNAME", ""),
    "username": os.getenv("CPANEL_USERNAME", ""),
    "token": os.getenv("CPANEL_TOKEN", ""),
}

skip_unless_cpanel = pytest.mark.skipif(
    not all(CREDENTIALS.values()),
    reason="set CPANEL_HOSTNAME, CPANEL_USERNAME and CPANEL_TOKEN to run",
)
skip_unless_writes = pytest.mark.skipif(
    os.getenv("CPANEL_ALLOW_WRITES") != "1",
    reason="set CPANEL_ALLOW_WRITES=1 on a DISPOSABLE account to run write tests",
)

pytestmark = [pytest.mark.integration, skip_unless_cpanel]


@pytest.fixture
def adapter():
    return CpanelAdapter(credentials=CREDENTIALS, config={})


def test_connection(adapter):
    assert adapter.test_connection().success is True


def test_account(adapter):
    account = adapter.get_account()
    assert isinstance(account, HostingAccount)
    assert account.username == CREDENTIALS["username"]


def test_usage_reports_disk(adapter):
    keys = {r.key for r in adapter.get_usage()}
    assert "disk_usage" in keys


def test_domains_and_zone_round_trip(adapter):
    domains = adapter.list_domains()
    assert domains
    snapshot = adapter.get_zone(domains[0].domain)
    assert snapshot.version, "the zone must report a serial"
    assert snapshot.records


def test_mailboxes_are_listed_in_bytes(adapter):
    for box in adapter.list_mailboxes():
        assert box.disk_used is None or box.disk_used >= 0


@skip_unless_writes
def test_create_and_delete_mailbox(adapter):
    email = "bapp-connectors-probe@" + adapter.get_account().primary_domain
    try:
        adapter.create_mailbox(email, "Corect-Cal-Baterie-Capsator-9", quota_mb=10)
        assert any(b.email == email for b in adapter.list_mailboxes())
    finally:
        adapter.delete_mailbox(email)
    assert not any(b.email == email for b in adapter.list_mailboxes())
