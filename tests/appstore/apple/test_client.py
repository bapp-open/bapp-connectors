"""Clientul HTTP Apple: parametrii exacti ai rapoartelor si tratarea 404 (raport nepublicat)."""

from __future__ import annotations

import pytest

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError
from bapp_connectors.providers.appstore.apple.client import AppleApiClient
from tests.appstore.conftest import FakeResponse
from tests.fake_http import FakeHttpClient


@pytest.fixture
def fake_http() -> FakeHttpClient:
    return FakeHttpClient(base_url="https://api.appstoreconnect.apple.com/v1/")


@pytest.fixture
def client(fake_http) -> AppleApiClient:
    return AppleApiClient(http_client=fake_http, vendor_number="88888888")


def test_sales_report_request_params(fake_http, client):
    fake_http.add("GET", "salesReports", FakeResponse(content=b"gz"))
    assert client.download_sales_report("2026-09-01") == b"gz"
    call = fake_http.last_call()
    assert call.kwargs["params"] == {
        "filter[frequency]": "DAILY",
        "filter[reportDate]": "2026-09-01",
        "filter[reportSubType]": "SUMMARY",
        "filter[reportType]": "SALES",
        "filter[vendorNumber]": "88888888",
        "filter[version]": "1_1",
    }
    assert call.kwargs["headers"]["Accept"] == "application/a-gzip"
    assert call.kwargs["direct_response"] is True


def test_finance_report_request_params(fake_http, client):
    fake_http.add("GET", "financeReports", FakeResponse(content=b"gz"))
    assert client.download_finance_report("2026-09") == b"gz"
    assert fake_http.last_call().kwargs["params"] == {
        "filter[regionCode]": "Z1",
        "filter[reportDate]": "2026-09",
        "filter[reportType]": "FINANCE_DETAIL",
        "filter[vendorNumber]": "88888888",
    }


def test_missing_report_returns_none(fake_http, client):
    fake_http.add("GET", "salesReports", FakeResponse(status_code=404, text="no sales"))
    assert client.download_sales_report("2026-09-01") is None


def test_gone_report_returns_none(fake_http, client):
    """410 GONE: rapoartele zilnice de vanzari exista doar 365 de zile."""
    fake_http.add("GET", "salesReports", FakeResponse(status_code=410, text="GONE_ERROR Report is no longer available"))
    assert client.download_sales_report("2024-09-29") is None


def test_auth_failure_raises(fake_http, client):
    fake_http.add("GET", "financeReports", FakeResponse(status_code=401, text="NOT_AUTHORIZED"))
    with pytest.raises(AuthenticationError):
        client.download_finance_report("2026-09")


def test_bad_version_raises_permanent_with_body(fake_http, client):
    fake_http.add("GET", "salesReports", FakeResponse(status_code=400, text="version 1_1 is not valid"))
    with pytest.raises(PermanentProviderError, match="version 1_1"):
        client.download_sales_report("2026-09-01")


def test_list_apps_follows_next_links(fake_http, client):
    fake_http.add(
        "GET",
        "https://api.appstoreconnect.apple.com/v1/apps?cursor=2",
        {"data": [{"id": "2", "attributes": {"name": "B", "bundleId": "b"}}], "links": {}},
    )
    fake_http.add(
        "GET",
        "apps",
        {
            "data": [{"id": "1", "attributes": {"name": "A", "bundleId": "a"}}],
            "links": {"next": "https://api.appstoreconnect.apple.com/v1/apps?cursor=2"},
        },
    )
    apps = client.list_apps()
    assert [a["id"] for a in apps] == ["1", "2"]


def test_create_review_response_body(fake_http, client):
    fake_http.add("POST", "customerReviewResponses", {"data": {"id": "resp1", "attributes": {"responseBody": "Multumim"}}})
    client.create_review_response("rev1", "Multumim")
    body = fake_http.last_call().kwargs["json"]
    assert body["data"]["type"] == "customerReviewResponses"
    assert body["data"]["attributes"]["responseBody"] == "Multumim"
    assert body["data"]["relationships"]["review"]["data"] == {"type": "customerReviews", "id": "rev1"}
