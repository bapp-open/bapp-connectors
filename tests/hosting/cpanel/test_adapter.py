"""Adapter tests against canned UAPI responses."""

import json
from pathlib import Path

import pytest

from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability
from bapp_connectors.core.ports import HostingPort
from bapp_connectors.providers.hosting.cpanel.adapter import CpanelAdapter
from tests.fake_http import FakeHttpClient
from tests.hosting.contract import HostingContractTests

FIXTURES = Path(__file__).parent / "fixtures"

CREDENTIALS = {"hostname": "cpanel.example.net", "username": "exampleuser", "token": "not-a-real-token"}


def envelope(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def build_http() -> FakeHttpClient:
    http = FakeHttpClient()
    http.add("GET", "DomainInfo/domains_data", envelope("domains_data"))
    http.add("GET", "SSL/installed_hosts", envelope("ssl_hosts"))
    http.add("GET", "ResourceUsage/get_usages", envelope("usages"))
    http.add("GET", "Quota/get_quota_info", envelope("quota"))
    http.add("GET", "Email/list_pops_with_disk", envelope("pops_disk"))
    http.add("GET", "DNS/parse_zone", envelope("zone"))
    http.add(
        "GET",
        "DomainInfo/list_domains",
        {"status": 1, "errors": None, "data": {"main_domain": "example.test"}},
    )
    http.add(
        "GET",
        "Variables/get_user_information",
        {"status": 1, "errors": None, "data": {"user": "exampleuser", "plan": "starter"}},
    )
    http.add(
        "GET",
        "Session/create_webmail_session_for_self",
        {"status": 1, "errors": None, "data": {"session": "exampleuser:abc:TOKEN,deadbeef", "token": "/cpsess1"}},
    )
    http.add("POST", "Email/add_pop", {"status": 1, "errors": None, "data": {}})
    http.add("POST", "Email/delete_pop", {"status": 1, "errors": None, "data": {}})
    return http


@pytest.fixture
def http():
    return build_http()


@pytest.fixture
def adapter(http):
    return CpanelAdapter(credentials=CREDENTIALS, http_client=http, config={})


class TestCpanelHostingContract(HostingContractTests):
    @pytest.fixture
    def adapter(self, http):
        return CpanelAdapter(credentials=CREDENTIALS, http_client=http, config={})


def test_declares_the_interfaces_its_manifest_claims(adapter):
    for interface in (HostingPort, MailboxCapability, PanelLinkCapability):
        assert isinstance(adapter, interface)
        assert adapter.supports(interface)


def test_list_domains_merges_ssl(adapter):
    main = adapter.list_domains()[0]
    assert main.domain == "example.test"
    assert main.ssl_expires_at is not None


def test_list_mailboxes_returns_bytes(adapter):
    boxes = {b.email: b for b in adapter.list_mailboxes()}
    assert boxes["admin@example.test"].disk_quota == 1073741824


def test_panel_link_is_honest_about_not_being_single_sign_on(adapter):
    link = adapter.get_panel_link()
    assert link.kind == "panel"
    assert link.url == "https://cpanel.example.net:2083/"
    assert link.single_sign_on is False


def test_webmail_link_is_single_sign_on(adapter):
    link = adapter.get_webmail_link()
    assert link.kind == "webmail"
    assert link.single_sign_on is True
    assert link.url.startswith("https://cpanel.example.net:2096/login/?session=")


def test_create_mailbox_posts_and_rereads(adapter, http):
    adapter.create_mailbox("new@example.test", "a-strong-passphrase", quota_mb=512)
    post = next(c for c in http.calls if c.method == "POST")
    assert post.kwargs["data"]["email"] == "new"
    assert post.kwargs["data"]["domain"] == "example.test"
    assert post.kwargs["data"]["quota"] == 512


def test_create_mailbox_with_no_quota_sends_unlimited(adapter, http):
    adapter.create_mailbox("new@example.test", "a-strong-passphrase")
    post = next(c for c in http.calls if c.method == "POST")
    assert post.kwargs["data"]["quota"] == 0, "cPanel spells unlimited as 0"
