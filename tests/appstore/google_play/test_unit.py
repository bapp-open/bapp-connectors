"""Adapterul Google Play cu bucket simulat: luni ca pagini, UTF-16 la recenzii, luna lipsa = pagina goala."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from bapp_connectors.core.dto import AppStoreProductType
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.providers.appstore.google_play.adapter import GooglePlayAdapter
from bapp_connectors.providers.appstore.google_play.manifest import manifest
from tests.appstore.conftest import FakeResponse
from tests.appstore.contract import AppStoreContractTests
from tests.appstore.google_play.test_mappers import EARNINGS_BASE, SALES_ROW
from tests.fake_http import FakeHttpClient

SERVICE_ACCOUNT = '{"type":"service_account","client_email":"sa@p.iam.gserviceaccount.com","private_key":"-----BEGIN PRIVATE KEY-----\\nx\\n-----END PRIVATE KEY-----","token_uri":"https://oauth2.googleapis.com/token"}'
CREDENTIALS = {"service_account_json": SERVICE_ACCOUNT, "bucket_uri": "gs://pubsite_prod_rev_123", "package_names": "ro.cbsoft.app"}


def _zip_csv(name: str, rows: list[dict]) -> bytes:
    header = ",".join(rows[0].keys())
    lines = [header] + [",".join(f'"{v}"' for v in r.values()) for r in rows]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, "\n".join(lines))
    return buffer.getvalue()


REVIEW_CSV = (
    "Package Name,App Version Code,App Version Name,Reviewer Language,Device,Review Submit Date and Time,Review Submit Millis Since Epoch,"
    "Review Last Update Date and Time,Review Last Update Millis Since Epoch,Star Rating,Review Title,Review Text,Developer Reply Date and Time,"
    "Developer Reply Millis Since Epoch,Developer Reply Text,Review Link\n"
    "ro.cbsoft.app,210,2.1,ro,Pixel 8,2026-09-10T10:00:00Z,1789120800000,2026-09-10T10:00:00Z,1789120800000,5,,Excelent,,,,"
    "https://play.google.com/console/x?reviewId=gp%3AAOqpTOE\n"
).encode("utf-16")


def _utf16(header: str, *lines: str) -> bytes:
    return ("\n".join([header, *lines]) + "\n").encode("utf-16")


_INSTALLS_HEAD = (
    "Daily Device Installs,Daily Device Uninstalls,Daily Device Upgrades,Total User Installs,Daily User Installs,"
    "Daily User Uninstalls,Active Device Installs,Install events,Update events,Uninstall events"
)
INSTALLS_OVERVIEW = _utf16(
    f"Date,Package name,{_INSTALLS_HEAD}",
    "2026-09-02,ro.cbsoft.app,12,3,40,900,11,2,500,14,41,4",
    "2026-09-03,ro.cbsoft.app,5,1,20,905,5,1,505,6,21,1",
    "2026-09-20,ro.cbsoft.app,9,9,9,9,9,9,9,9,9,9",
)
INSTALLS_COUNTRY = _utf16(
    f"Date,Package name,Country,{_INSTALLS_HEAD}",
    "2026-09-02,ro.cbsoft.app,RO,10,2,30,800,9,1,400,11,31,3",
    "2026-09-03,ro.cbsoft.app,DE,2,1,10,100,2,1,100,3,10,1",
)
RATINGS_OVERVIEW = _utf16(
    "Date,Package Name,Daily Average Rating,Total Average Rating",
    "2026-09-02,ro.cbsoft.app,4.5,4.31",
    "2026-09-03,ro.cbsoft.app,,4.31",
)
CRASHES_OVERVIEW = _utf16(
    "Date,Package Name,Daily Crashes,Daily ANRs",
    "2026-09-02,ro.cbsoft.app,2,1",
    "2026-09-20,ro.cbsoft.app,7,7",
)
STORE_TRAFFIC = _utf16(
    "Date,Package name,Traffic source,Total store acquisitions",
    "2026-09-02,ro.cbsoft.app,Google Search,7",
)


@pytest.fixture
def fake_http():
    fake = FakeHttpClient(base_url=manifest.base_url)
    objects = {
        "earnings/earnings_202609_1.zip": _zip_csv("earnings.csv", [EARNINGS_BASE, {**EARNINGS_BASE, "Transaction Type": "Google fee", "Amount (Merchant Currency)": "-0.90"}]),
        "sales/salesreport_202609.zip": _zip_csv("salesreport_202609.csv", [SALES_ROW, {**SALES_ROW, "Order Number": "GPA.2", "Financial Status": "Refund"}]),
        "reviews/reviews_ro.cbsoft.app_202609.csv": REVIEW_CSV,
        "stats/installs/installs_ro.cbsoft.app_202609_overview.csv": INSTALLS_OVERVIEW,
        "stats/installs/installs_ro.cbsoft.app_202609_country.csv": INSTALLS_COUNTRY,
        "stats/ratings/ratings_ro.cbsoft.app_202609_overview.csv": RATINGS_OVERVIEW,
        "stats/crashes/crashes_ro.cbsoft.app_202609_overview.csv": CRASHES_OVERVIEW,
        "stats/store_performance/total_store_performance_ro.cbsoft.app_202609_traffic_source.csv": STORE_TRAFFIC,
    }

    def list_objects(method, path, kwargs):
        prefix = kwargs["params"].get("prefix", "")
        return {"items": [{"name": n} for n in objects if n.startswith(prefix)]}

    def download(method, path, kwargs):
        from urllib.parse import unquote

        name = unquote(path.split("/o/")[1])
        if name in objects:
            return FakeResponse(content=objects[name])
        return FakeResponse(status_code=404, text="not found")

    fake.add("GET", "/o/", download)
    fake.add("GET", "b/pubsite_prod_rev_123/o", list_objects)
    fake.add("GET", "/reviews", {"reviews": [{"reviewId": "gp:NEW", "authorName": "Ana", "comments": [{"userComment": {"text": "Nou", "lastModified": {"seconds": "1789300000"}, "starRating": 4}}]}]})
    fake.add("POST", ":reply", {"result": {"replyText": "Mersi", "lastEdited": {"seconds": "1789400000"}}})
    fake.add("GET", "voidedpurchases", {"voidedPurchases": [{"purchaseToken": "tok", "orderId": "GPA.9", "purchaseTimeMillis": "1789120800000", "voidedTimeMillis": "1789207200000", "voidedReason": 1}]})
    fake.add("GET", "subscriptionsv2/tokens/tok", {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE", "lineItems": [{"productId": "pro_monthly", "expiryTime": "2026-10-03T10:00:00Z"}]})
    return fake


@pytest.fixture
def adapter(fake_http):
    a = GooglePlayAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)
    a.auth._fetch = lambda uri, assertion: {"access_token": "t", "expires_in": 3600}  # fara retea
    return a


class TestGooglePlayContract(AppStoreContractTests):
    @pytest.fixture
    def adapter(self, adapter):
        return adapter

    @pytest.fixture
    def sales_window(self):
        return date(2026, 9, 1), date(2026, 9, 30)

    @pytest.fixture
    def expected_net(self):
        return Decimal("5.13")  # 6.03 - 0.90

    @pytest.fixture
    def review_app_id(self):
        return "ro.cbsoft.app"

    @pytest.fixture
    def stats_window(self):
        return date(2026, 9, 1), date(2026, 9, 30)


def test_sales_month_page_marks_refund(adapter):
    page = adapter.get_sales(date(2026, 9, 1), date(2026, 9, 30))
    assert page.has_more is False
    assert [s.is_refund for s in page.items] == [False, True]
    assert page.items[0].product_type == AppStoreProductType.SUBSCRIPTION


def test_app_stats_month_page(adapter):
    page = adapter.get_app_stats("ro.cbsoft.app", date(2026, 9, 2), date(2026, 9, 3))
    assert page.has_more is False
    assert all(date(2026, 9, 2) <= s.date <= date(2026, 9, 3) for s in page.items)  # 20.09 taiat
    values = {(s.metric.value, s.date.day, s.country, s.extra.get("traffic_source", "")): s.value for s in page.items}
    assert values[("installs", 2, "", "")] == Decimal("12")
    assert values[("active_devices", 3, "", "")] == Decimal("505")
    assert values[("installs", 2, "RO", "")] == Decimal("10")
    assert values[("installs", 3, "DE", "")] == Decimal("2")
    assert values[("rating_daily", 2, "", "")] == Decimal("4.5")
    assert ("rating_daily", 3, "", "") not in values
    assert values[("rating_total", 3, "", "")] == Decimal("4.31")
    assert values[("crashes", 2, "", "")] == Decimal("2")
    assert values[("anrs", 2, "", "")] == Decimal("1")
    assert values[("store_acquisitions", 2, "", "Google Search")] == Decimal("7")
    assert ("crashes", 20, "", "") not in values
    assert len({s.external_key for s in page.items}) == len(page.items)


def test_app_stats_missing_month_is_empty_page(adapter):
    page = adapter.get_app_stats("ro.cbsoft.app", date(2026, 10, 1), date(2026, 10, 31))
    assert page.items == [] and page.has_more is False


def test_earnings_missing_month_is_empty_page(adapter):
    page = adapter.get_financial_transactions(datetime(2026, 10, 1), datetime(2026, 10, 31))
    assert page.items == [] and page.has_more is False


def test_reviews_merge_csv_history_with_live_api(adapter):
    ids: list[str] = []
    cursor = None
    while True:
        page = adapter.list_reviews("ro.cbsoft.app", since=datetime(2026, 9, 1), cursor=cursor)
        ids.extend(r.review_id for r in page.items)
        cursor = page.cursor
        if not page.has_more:
            break
    assert sorted(ids) == ["gp:AOqpTOE", "gp:NEW"]  # fiecare exact o data
    first = adapter.list_reviews("ro.cbsoft.app", since=datetime(2026, 9, 1))
    csv_review = next(r for r in first.items if r.review_id == "gp:AOqpTOE")
    assert csv_review.body == "Excelent"


def _month_objects_adapter(names):
    def list_objects(method, path, kwargs):
        prefix = kwargs["params"].get("prefix", "")
        return {"items": [{"name": n} for n in names if n.startswith(prefix)]}

    fake = FakeHttpClient(base_url=manifest.base_url)
    fake.add("GET", "b/pubsite_prod_rev_123/o", list_objects)
    a = GooglePlayAdapter(credentials=dict(CREDENTIALS), http_client=fake)
    a.auth._fetch = lambda uri, assertion: {"access_token": "t", "expires_in": 3600}
    return a


def test_month_objects_with_digits_in_package_name():
    a = _month_objects_adapter(
        [
            "reviews/reviews_com.foo_123456.app_202609.csv",
            "reviews/reviews_com.foo_202512_202609.csv",
            "earnings/earnings_202609_1.zip",
            "earnings/earnings_202609_abc-1.zip",
            "earnings/earnings_202608_1.zip",
            "sales/salesreport_202609.zip",
            "sales/salesreport_202608.zip",
        ]
    )
    assert a._month_objects("reviews/reviews_com.foo_123456.app_", 2026, 9) == ["reviews/reviews_com.foo_123456.app_202609.csv"]
    # Pachetul `com.foo_202512` nu e luat drept luna decembrie: stamp-ul e cel de dupa prefixul pachetului.
    assert a._month_objects("reviews/reviews_com.foo_202512_", 2026, 9) == ["reviews/reviews_com.foo_202512_202609.csv"]
    assert a._month_objects("reviews/reviews_com.foo_123456.app_", 2026, 12) == []
    assert a._month_objects("earnings/", 2026, 9) == ["earnings/earnings_202609_1.zip", "earnings/earnings_202609_abc-1.zip"]
    assert a._month_objects("sales/", 2026, 9) == ["sales/salesreport_202609.zip"]


def test_month_objects_empty_prefix_is_empty():
    assert _month_objects_adapter([])._month_objects("sales/", 2026, 9) == []


def test_month_objects_without_any_recognizable_stamp_raises():
    a = _month_objects_adapter(["sales/sales_report_sept.zip", "sales/README.txt"])
    with pytest.raises(PermanentProviderError, match="stamp YYYYMM"):
        a._month_objects("sales/", 2026, 9)


def test_reply_and_refunds_and_subscription(adapter):
    assert adapter.reply_to_review("ro.cbsoft.app", "gp:NEW", "Mersi").developer_response == "Mersi"
    with patch("time.time", return_value=datetime(2026, 9, 30, 12, tzinfo=UTC).timestamp()):
        refunds = adapter.list_refunds(date(2026, 9, 1), date(2026, 9, 30))
    assert refunds.items[0].refund_id == "GPA.9"
    assert adapter.get_subscription("ro.cbsoft.app:tok").price_id == "pro_monthly"


def test_without_package_names_publisher_calls_are_not_implemented(fake_http):
    a = GooglePlayAdapter(credentials={"service_account_json": SERVICE_ACCOUNT, "bucket_uri": "gs://pubsite_prod_rev_123"}, http_client=fake_http)
    with pytest.raises(NotImplementedError, match="package_names"):
        a.reply_to_review("ro.cbsoft.app", "x", "y")


def _voided_params(fake_http):
    return [c.kwargs["params"] for c in fake_http.calls if "voidedpurchases" in c.path]


def test_list_refunds_clamps_end_to_now(adapter, fake_http):
    now = datetime(2026, 9, 30, 12, tzinfo=UTC).timestamp()
    with patch("time.time", return_value=now):
        adapter.list_refunds(date(2026, 9, 25), date(2026, 9, 30))
    params = _voided_params(fake_http)[0]
    assert int(params["endTime"]) < int(now * 1000)


def test_list_refunds_clamps_start_to_lookback(adapter, fake_http):
    now = datetime(2026, 9, 30, 12, tzinfo=UTC).timestamp()
    with patch("time.time", return_value=now):
        adapter.list_refunds(date(2026, 6, 1), date(2026, 9, 29))
    params = _voided_params(fake_http)[0]
    assert int(params["startTime"]) == int(now * 1000) - 29 * 86400 * 1000


def test_list_refunds_window_entirely_too_old_is_empty(adapter, fake_http):
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    old = (now - timedelta(days=60)).date()
    with patch("time.time", return_value=now.timestamp()):
        page = adapter.list_refunds(old, old)
    assert page.items == [] and page.has_more is False
    assert _voided_params(fake_http) == []
