"""Adapterul Google Play cu bucket simulat: luni ca pagini, UTF-16 la recenzii, luna lipsa = pagina goala."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import AppStoreProductType
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


@pytest.fixture
def fake_http():
    fake = FakeHttpClient(base_url=manifest.base_url)
    objects = {
        "earnings/earnings_202609_1.zip": _zip_csv("earnings.csv", [EARNINGS_BASE, {**EARNINGS_BASE, "Transaction Type": "Google fee", "Amount (Merchant Currency)": "-0.90"}]),
        "sales/salesreport_202609.zip": _zip_csv("salesreport_202609.csv", [SALES_ROW, {**SALES_ROW, "Order Number": "GPA.2", "Financial Status": "Refund"}]),
        "reviews/reviews_ro.cbsoft.app_202609.csv": REVIEW_CSV,
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
    def unsupported_methods(self):
        return set()


def test_sales_month_page_marks_refund(adapter):
    page = adapter.get_sales(date(2026, 9, 1), date(2026, 9, 30))
    assert page.has_more is False
    assert [s.is_refund for s in page.items] == [False, True]
    assert page.items[0].product_type == AppStoreProductType.SUBSCRIPTION


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


def test_month_objects_with_digits_in_package_name(fake_http):
    extra = {
        "reviews/reviews_com.foo_123456.app_202609.csv": b"x",
        "earnings/earnings_202609_1.zip": b"x",
    }

    def list_objects(method, path, kwargs):
        prefix = kwargs["params"].get("prefix", "")
        return {"items": [{"name": n} for n in extra if n.startswith(prefix)]}

    fake = FakeHttpClient(base_url=manifest.base_url)
    fake.add("GET", "b/pubsite_prod_rev_123/o", list_objects)
    a = GooglePlayAdapter(credentials=dict(CREDENTIALS), http_client=fake)
    a.auth._fetch = lambda uri, assertion: {"access_token": "t", "expires_in": 3600}
    assert a._month_objects("reviews/", 2026, 9) == ["reviews/reviews_com.foo_123456.app_202609.csv"]
    assert a._month_objects("earnings/", 2026, 9) == ["earnings/earnings_202609_1.zip"]
    assert a._month_objects("reviews/", 2026, 12) == []
    assert a._month_objects("reviews/", 2026, 12) == []


def test_reply_and_refunds_and_subscription(adapter):
    assert adapter.reply_to_review("ro.cbsoft.app", "gp:NEW", "Mersi").developer_response == "Mersi"
    refunds = adapter.list_refunds(date(2026, 9, 1), date(2026, 9, 30))
    assert refunds.items[0].refund_id == "GPA.9"
    assert adapter.get_subscription("ro.cbsoft.app:tok").price_id == "pro_monthly"


def test_without_package_names_publisher_calls_are_not_implemented(fake_http):
    a = GooglePlayAdapter(credentials={"service_account_json": SERVICE_ACCOUNT, "bucket_uri": "gs://pubsite_prod_rev_123"}, http_client=fake_http)
    with pytest.raises(NotImplementedError, match="package_names"):
        a.reply_to_review("ro.cbsoft.app", "x", "y")
