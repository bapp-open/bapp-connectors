"""The envelope, not the HTTP status, decides success."""

import pytest

from bapp_connectors.providers.hosting.cpanel.client import CpanelUapiClient
from bapp_connectors.providers.hosting.cpanel.errors import (
    CpanelNotFoundError,
    CpanelWeakPasswordError,
    DnsZoneChangedError,
)
from tests.fake_http import FakeHttpClient


def make_client(response):
    http = FakeHttpClient()
    http.add(None, "execute/", response)
    client = CpanelUapiClient(
        http_client=http, hostname="cpanel.example.net", username="exampleuser", token="tok"
    )
    return client, http


def test_unwraps_data_on_success():
    client, _ = make_client({"status": 1, "data": {"main_domain": "example.test"}, "errors": None})
    assert client.call("DomainInfo", "list_domains") == {"main_domain": "example.test"}


def test_status_zero_raises_even_though_http_was_200():
    # A failed UAPI call is HTTP 200 with status 0. Trusting the HTTP status turns
    # every failure into a silent success.
    client, _ = make_client(
        {"status": 0, "data": None, "errors": ['You do not have an email account named "ghost@example.test".']}
    )
    with pytest.raises(CpanelNotFoundError):
        client.call("Email", "delete_pop", email="ghost@example.test")


def test_weak_password_is_its_own_error():
    client, _ = make_client(
        {"status": 0, "data": None, "errors": ['The password that you entered has a strength rating of "0".']}
    )
    with pytest.raises(CpanelWeakPasswordError):
        client.call("Email", "passwd_pop", method="POST", email="a@example.test", password="x")


def test_stale_serial_is_its_own_error():
    client, _ = make_client(
        {
            "status": 0,
            "data": None,
            "errors": ["The given serial number (1) does not match the DNS zone's serial number (2026010101)."],
        }
    )
    with pytest.raises(DnsZoneChangedError):
        client.call("DNS", "mass_edit_zone", method="POST", zone="example.test", serial="1")


def test_reads_use_get_with_query_params():
    client, http = make_client({"status": 1, "data": [], "errors": None})
    client.call("Email", "list_pops_with_disk", domain="example.test")
    call = http.calls[-1]
    assert call.method == "GET"
    assert call.path == "https://cpanel.example.net:2083/execute/Email/list_pops_with_disk"
    assert call.kwargs["params"] == {"domain": "example.test"}


def test_writes_use_post_body_so_passwords_never_reach_the_url():
    client, http = make_client({"status": 1, "data": {}, "errors": None})
    client.call("Email", "add_pop", method="POST", email="a@example.test", password="hunter2")
    call = http.calls[-1]
    assert call.method == "POST"
    assert "params" not in call.kwargs or call.kwargs["params"] is None
    assert call.kwargs["data"] == {"email": "a@example.test", "password": "hunter2"}


def test_none_params_are_dropped():
    client, http = make_client({"status": 1, "data": [], "errors": None})
    client.call("Email", "list_pops_with_disk", domain=None)
    assert http.calls[-1].kwargs["params"] == {}


def test_url_is_absolute_so_the_injected_client_base_url_cannot_redirect_it():
    client, http = make_client({"status": 1, "data": [], "errors": None})
    client.call("DomainInfo", "list_domains")
    assert http.calls[-1].path == "https://cpanel.example.net:2083/execute/DomainInfo/list_domains"


def test_authorization_header_is_set_by_the_client_itself():
    client, http = make_client({"status": 1, "data": [], "errors": None})
    client.call("DomainInfo", "list_domains")
    assert http.calls[-1].kwargs["headers"]["Authorization"] == "cpanel exampleuser:tok"
