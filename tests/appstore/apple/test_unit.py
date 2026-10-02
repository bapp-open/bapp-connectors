"""Adapterul Apple cu HTTP simulat: rapoarte gzip, paginare pe zile, luni fiscale."""

from __future__ import annotations

import gzip
from datetime import date, datetime
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import AppStoreProductType
from bapp_connectors.providers.appstore.apple.adapter import AppleAppStoreAdapter
from bapp_connectors.providers.appstore.apple.manifest import manifest
from tests.appstore.conftest import FakeResponse
from tests.appstore.contract import AppStoreContractTests
from tests.fake_http import FakeHttpClient

CREDENTIALS = {
    "issuer_id": "iss",
    "key_id": "kid",
    "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----",
    "vendor_number": "88888888",
}

SALES_HEADER = "\t".join(
    [
        "Provider",
        "Provider Country",
        "SKU",
        "Developer",
        "Title",
        "Version",
        "Product Type Identifier",
        "Units",
        "Developer Proceeds",
        "Begin Date",
        "End Date",
        "Customer Currency",
        "Country Code",
        "Currency of Proceeds",
        "Apple Identifier",
        "Customer Price",
        "Promo Code",
        "Parent Identifier",
        "Subscription",
        "Period",
        "Category",
        "CMB",
        "Device",
        "Supported Platforms",
        "Proceeds Reason",
        "Preserved Pricing",
        "Client",
        "Order Type",
    ]
)


def _sales_tsv(day: str, units: str, proceeds: str) -> bytes:
    row = "\t".join(
        [
            "APPLE",
            "US",
            "ro.cbsoft.pro.monthly",
            "CBSoft",
            "BAPP Pro",
            "2.1",
            "IAY",
            units,
            proceeds,
            day,
            day,
            "EUR",
            "RO",
            "EUR",
            "645",
            "5.99",
            "",
            "ro.cbsoft.app",
            "Renewal",
            "1 Month",
            "Business",
            "",
            "iPhone",
            "iOS",
            "",
            "",
            "",
            "",
        ]
    )
    return gzip.compress(f"{SALES_HEADER}\n{row}\nTotal_Rows\t1\n".encode())


FINANCE_HEADER = "\t".join(
    [
        "Transaction Date",
        "Settlement Date",
        "Apple Identifier",
        "SKU",
        "Title",
        "Developer Name",
        "Product Type Identifier",
        "Country of Sale",
        "Quantity",
        "Partner Share",
        "Extended Partner Share",
        "Partner Share Currency",
        "Customer Price",
        "Customer Currency",
        "Sale or Return",
        "Promo Code",
        "Order Type",
        "Region",
    ]
)


def _finance_tsv(rows: list[tuple[str, str, str, str]]) -> bytes:
    lines = ["Vendor Name\tCBSoft", "Start Date\t08/30/2026", "End Date\t09/26/2026", FINANCE_HEADER]
    for qty, share, ext, sale_or_return in rows:
        lines.append(
            "\t".join(
                [
                    "09/03/2026",
                    "09/26/2026",
                    "645",
                    "ro.cbsoft.pro.monthly",
                    "BAPP Pro",
                    "CBSoft",
                    "IAY",
                    "RO",
                    qty,
                    share,
                    ext,
                    "EUR",
                    "5.99",
                    "EUR",
                    sale_or_return,
                    "",
                    "",
                    "",
                    "",  # celula goala de la coada, ca in fisierul real
                ]
            )
        )
    lines += ["Country Of Sale\tPartner Share Currency\tQuantity\tExtended Partner Share", "RO\tEUR\t2\t8.52"]
    return gzip.compress("\n".join(lines).encode())


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient(base_url=manifest.base_url)

    def sales(method, path, kwargs):
        day = kwargs["params"]["filter[reportDate]"]
        if day == "2026-09-02":
            return FakeResponse(status_code=404, text="no sales")
        mdy = f"{day[5:7]}/{day[8:10]}/{day[0:4]}"
        return FakeResponse(content=_sales_tsv(mdy, "-1" if day == "2026-09-03" else "3", "4.26"))

    def finance(method, path, kwargs):
        period = kwargs["params"]["filter[reportDate]"]
        if period == "2026-12":  # Apple: an fiscal 2026, luna 12 = etichetea noastra "2026-09"
            return FakeResponse(content=_finance_tsv([("3", "4.26", "12.78", "S"), ("-1", "4.26", "-4.26", "R")]))
        return FakeResponse(status_code=404, text="not available")

    fake.add("GET", "salesReports", sales)
    fake.add("GET", "financeReports", finance)
    fake.add(
        "GET",
        "apps/645/customerReviews",
        {
            "data": [
                {
                    "id": "r1",
                    "attributes": {
                        "rating": 5,
                        "title": "Top",
                        "body": "Merge",
                        "reviewerNickname": "Ana",
                        "createdDate": "2026-09-10T10:00:00Z",
                        "territory": "ROU",
                    },
                    "relationships": {"response": {"data": None}},
                }
            ],
            "included": [],
            "links": {},
        },
    )
    fake.add(
        "GET",
        "apps",
        {
            "data": [{"id": "645", "attributes": {"name": "BAPP", "bundleId": "ro.cbsoft.app", "sku": "BAPP"}}],
            "links": {},
        },
    )
    fake.add(
        "POST",
        "customerReviewResponses",
        {
            "data": {
                "id": "resp1",
                "attributes": {
                    "responseBody": "Multumim",
                    "lastModifiedDate": "2026-09-11T08:00:00Z",
                    "state": "PUBLISHED",
                },
            }
        },
    )
    return fake


@pytest.fixture
def adapter(fake_http) -> AppleAppStoreAdapter:
    return AppleAppStoreAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)


class TestAppleContract(AppStoreContractTests):
    @pytest.fixture
    def adapter(self, fake_http):
        return AppleAppStoreAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)

    @pytest.fixture
    def sales_window(self):
        return date(2026, 9, 1), date(2026, 9, 3)

    @pytest.fixture
    def expected_net(self):
        return Decimal("8.52")  # 12.78 - 4.26, luna fiscala 2026-09

    @pytest.fixture
    def review_app_id(self):
        return "645"

    @pytest.fixture
    def unsupported_methods(self):
        return {"get_subscription"}  # fixture-ul n-are cheie In-App Purchase


def test_sales_missing_report_is_empty_page(adapter):
    page = adapter.get_sales(date(2026, 9, 1), date(2026, 9, 3), cursor="2026-09-02")
    assert page.items == []
    assert page.has_more is True
    assert page.cursor == "2026-09-03"


def test_sales_one_day_per_page(adapter):
    page = adapter.get_sales(date(2026, 9, 1), date(2026, 9, 3))
    assert len(page.items) == 1
    assert page.items[0].product_type == AppStoreProductType.SUBSCRIPTION_RENEWAL
    assert page.cursor == "2026-09-02"


def test_refunds_come_from_negative_units(adapter):
    page = adapter.list_refunds(date(2026, 9, 3), date(2026, 9, 3))
    assert len(page.items) == 1
    assert page.items[0].amount == Decimal("5.99")


def test_financial_transactions_use_fiscal_months(adapter):
    page = adapter.get_financial_transactions(datetime(2026, 9, 20), datetime(2026, 10, 5))
    assert page.cursor == "2026-10"  # a doua luna fiscala
    assert {t.payout_id for t in page.items} == {"2026-09:EUR"}
    assert len(page.items) == 2
    assert {t.extra["period_start"] for t in page.items} == {"2026-08-30"}
    assert {t.extra["period_end"] for t in page.items} == {"2026-09-26"}
    page2 = adapter.get_financial_transactions(datetime(2026, 9, 20), datetime(2026, 10, 5), cursor="2026-10")
    assert page2.items == [] and page2.has_more is False


def test_reply_to_review(adapter):
    review = adapter.reply_to_review("645", "r1", "Multumim")
    assert review.developer_response == "Multumim"
    assert review.review_id == "r1"


def test_get_subscription_without_iap_key_is_not_implemented(adapter):
    with pytest.raises(NotImplementedError, match="In-App Purchase"):
        adapter.get_subscription("1000000")


def test_missing_credentials_fails_validation():
    assert AppleAppStoreAdapter(credentials={}).validate_credentials() is False


def test_unknown_fiscal_cursor_raises(adapter):
    with pytest.raises(ValueError, match="cursor fiscal necunoscut"):
        adapter.get_financial_transactions(datetime(2026, 9, 20), datetime(2026, 10, 5), cursor="2025-01")


def test_range_without_fiscal_months_raises(adapter):
    with pytest.raises(ValueError, match="nicio luna fiscala"):
        adapter.get_financial_transactions(datetime(2026, 10, 5), datetime(2026, 9, 20))
