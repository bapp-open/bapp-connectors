"""Adapterul Steam cu HTTP simulat: cheia in query, zile ca pagini, highwatermark, recenzii publice."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.providers.appstore.steam.adapter import SteamAdapter
from bapp_connectors.providers.appstore.steam.manifest import manifest
from tests.appstore.contract import AppStoreContractTests
from tests.appstore.steam.test_mappers import PAYLOAD, ROW
from tests.fake_http import FakeHttpClient

CREDENTIALS = {"financial_api_key": "ABCDEF0123456789", "app_ids": "4000, 4001"}


@pytest.fixture
def fake_http():
    fake = FakeHttpClient(base_url=manifest.base_url)

    def detailed(method, path, kwargs):
        params = kwargs["params"]
        assert params["key"] == "ABCDEF0123456789"
        if params["date"] == "2026-09-02":
            return {"response": {"results": [], "max_id": 0}}
        if int(params["highwatermark_id"]) == 0:
            return {"response": {**PAYLOAD, "max_id": 7}}
        return {"response": {"results": [{**ROW, "country_code": "DE"}], "max_id": 7, "app_info": PAYLOAD["app_info"], "package_info": PAYLOAD["package_info"]}}

    fake.add("GET", "GetDetailedSales", detailed)
    fake.add("GET", "GetChangedDatesForPartner", {"response": {"dates": ["2026-09-01", "2026-09-03"], "result_highwatermark": "99"}})
    fake.add("GET", "store.steampowered.com/api/appdetails", lambda m, p, k: {k["params"]["appids"]: {"success": True, "data": {"name": f"Game {k['params']['appids']}", "type": "game"}}})
    fake.add("GET", "store.steampowered.com/appreviews/4000", {"success": 1, "reviews": [{"recommendationid": "1", "author": {"steamid": "7"}, "language": "english", "review": "Nice", "timestamp_created": 1789120800, "voted_up": True}], "cursor": "AoJ4"})
    return fake


@pytest.fixture
def adapter(fake_http):
    return SteamAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)


class TestSteamContract(AppStoreContractTests):
    @pytest.fixture
    def adapter(self, adapter):
        return adapter

    @pytest.fixture
    def sales_window(self):
        return date(2026, 9, 1), date(2026, 9, 3)

    @pytest.fixture
    def expected_net(self):
        # 2 zile cu date (1 si 3), fiecare cu 2 randuri (RO + DE) a 105.79 net
        return Decimal("423.16")

    @pytest.fixture
    def review_app_id(self):
        return "4000"

    @pytest.fixture
    def stats_window(self):
        return date(2026, 9, 1), date(2026, 9, 3)

    @pytest.fixture
    def unsupported_methods(self):
        return {"reply_to_review", "get_subscription", "get_app_stats"}  # TODO Task C: Steam stats


def test_detailed_sales_drains_highwatermark(adapter):
    page = adapter.get_sales(date(2026, 9, 1), date(2026, 9, 1))
    assert {s.country for s in page.items} == {"RO", "DE"}
    assert page.has_more is False


def test_empty_day_is_empty_page(adapter):
    page = adapter.get_sales(date(2026, 9, 1), date(2026, 9, 3), cursor="2026-09-02")
    assert page.items == [] and page.cursor == "2026-09-03"


def test_changed_dates(adapter):
    days, watermark = adapter.changed_dates(0)
    assert days == [date(2026, 9, 1), date(2026, 9, 3)]
    assert watermark == 99


def test_list_apps_uses_public_app_details(adapter):
    apps = adapter.list_apps()
    assert [a.app_id for a in apps] == ["4000", "4001"]
    assert apps[0].name == "Game 4000"


def test_reviews_cursor_passthrough(adapter):
    page = adapter.list_reviews("4000")
    assert page.items[0].recommended is True
    assert page.cursor == "AoJ4" and page.has_more is True


def test_reply_and_subscription_not_supported(adapter):
    with pytest.raises(NotImplementedError):
        adapter.reply_to_review("4000", "1", "x")
    with pytest.raises(NotImplementedError):
        adapter.get_subscription("x")


def test_forbidden_mentions_ip_whitelist(fake_http):
    from bapp_connectors.core.errors import AuthenticationError

    def forbidden(method, path, kwargs):
        raise AuthenticationError("Authentication failed: 403 Forbidden", status_code=403)

    fake_http.responses.insert(0, ("GET", "GetChangedDatesForPartner", forbidden))
    adapter = SteamAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)
    result = adapter.test_connection()
    assert isinstance(result, ConnectionTestResult)
    assert result.success is False and "IP whitelist" in result.message


def test_changed_dates_accepts_slash_and_compact_formats(fake_http):
    fake_http.responses.insert(0, ("GET", "GetChangedDatesForPartner", {"response": {"dates": ["2026/09/01", "20260903"], "result_highwatermark": "5"}}))
    adapter = SteamAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)
    assert adapter.changed_dates(0) == ([date(2026, 9, 1), date(2026, 9, 3)], 5)


def test_detailed_sales_page_cap_raises(fake_http):
    from bapp_connectors.core.errors import PermanentProviderError

    def endless(method, path, kwargs):
        return {"response": {"results": [ROW], "max_id": int(kwargs["params"]["highwatermark_id"]) + 1}}

    fake_http.responses.insert(0, ("GET", "GetDetailedSales", endless))
    adapter = SteamAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)
    with pytest.raises(PermanentProviderError):
        adapter.get_sales(date(2026, 9, 1), date(2026, 9, 1))
