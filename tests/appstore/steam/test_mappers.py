"""Maparile Steam: GetDetailedSales -> vanzari / decontari / rambursari; appreviews -> recenzii."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from bapp_connectors.core.dto import AppStoreProductType, FinancialTransactionType
from bapp_connectors.providers.appstore.steam.mappers import (
    refunds_from_detailed,
    review_from_steam,
    sales_from_detailed,
    transactions_from_detailed,
)

ROW = {
    "partnerid": 1, "date": "2026-09-03", "line_item_type": "Package", "packageid": 500, "package_sale_type": "Steam", "platform": "Windows", "country_code": "RO",
    "base_price": "1999", "sale_price": "1999", "currency": "RON", "gross_units_sold": 10, "gross_units_returned": 1,
    "gross_sales_usd": "199.9000", "gross_returns_usd": "19.9900", "net_tax_usd": "28.7800", "primary_appid": 4000,
    "additional_revenue_share_tier": 0, "net_units_sold": 9, "net_sales_usd": "151.1300",
}
RETAIL_ROW = {
    "date": "2026-09-03", "line_item_type": "Package", "packageid": 1800669, "package_sale_type": "Retail", "platform": "Unknown", "country_code": "CA",
    "additional_revenue_share_tier": 0, "key_request_id": 1007134, "gross_units_activated": 5, "partnerid": 123,
}
PAYLOAD = {"results": [ROW], "max_id": 1, "app_info": [{"appid": 4000, "app_name": "Dungeon"}], "package_info": [{"packageid": 500, "package_name": "Dungeon - Standard"}]}


def test_sales_from_detailed():
    sales = sales_from_detailed(PAYLOAD, date(2026, 9, 3))
    assert len(sales) == 1
    sale = sales[0]
    assert sale.app_id == "4000"
    assert sale.product_name == "Dungeon - Standard"
    assert sale.product_type == AppStoreProductType.APP
    assert sale.units == Decimal("9")
    assert sale.customer_price == Decimal("19.99")
    assert sale.proceeds_currency == "USD"
    assert sale.proceeds_total == Decimal("151.13")
    assert sale.country == "RO"
    assert sale.customer_currency == "RON"
    assert sale.extra["gross_units_returned"] == 1


def test_transactions_sale_return_tax_commission():
    txs = transactions_from_detailed(PAYLOAD, date(2026, 9, 3))
    kinds = [t.transaction_type for t in txs]
    assert kinds == [FinancialTransactionType.SALE, FinancialTransactionType.RETURN, FinancialTransactionType.DEDUCTION, FinancialTransactionType.COMMISSION]
    assert txs[0].net_amount == Decimal("199.90")
    assert txs[1].net_amount == Decimal("-19.99")
    assert txs[2].net_amount == Decimal("-28.78")
    assert txs[3].net_amount == Decimal("-45.34")  # 30% din 151.13
    assert txs[3].extra["estimated"] is True
    assert {t.payout_id for t in txs} == {"2026-09:USD"}
    assert sum(t.net_amount for t in txs) == Decimal("105.79")


def test_commission_uses_bonus_tier():
    txs = transactions_from_detailed({**PAYLOAD, "results": [{**ROW, "additional_revenue_share_tier": 2}]}, date(2026, 9, 3))
    assert txs[-1].net_amount == Decimal("-30.23")  # 20%


def test_rows_without_returns_have_no_return_rows():
    txs = transactions_from_detailed({**PAYLOAD, "results": [{**ROW, "gross_units_returned": 0, "gross_returns_usd": "0", "net_tax_usd": "0"}]}, date(2026, 9, 3))
    assert [t.transaction_type for t in txs] == [FinancialTransactionType.SALE, FinancialTransactionType.COMMISSION]


def test_refunds_from_detailed():
    refunds = refunds_from_detailed(PAYLOAD, date(2026, 9, 3))
    assert len(refunds) == 1
    assert refunds[0].amount == Decimal("19.99")
    assert refunds[0].currency == "USD"
    assert refunds[0].extra["units"] == 1


def test_review_from_steam():
    data = {"recommendationid": "123", "author": {"steamid": "7656", "playtime_forever": 120}, "language": "romanian", "review": "Super joc", "timestamp_created": 1789120800, "timestamp_updated": 1789120800, "voted_up": True, "votes_up": 3}
    review = review_from_steam(data, "4000")
    assert review.review_id == "123"
    assert review.rating is None
    assert review.recommended is True
    assert review.language == "romanian"
    assert review.body == "Super joc"
    assert review.extra["playtime_minutes"] == 120


def test_row_key_discriminates_price_points():
    cheap = {**PAYLOAD, "results": [{**ROW, "sale_price": 999}]}
    full = sales_from_detailed(PAYLOAD, date(2026, 9, 3))[0]
    low = sales_from_detailed(cheap, date(2026, 9, 3))[0]
    assert full.external_key != low.external_key
    tx_full = transactions_from_detailed(PAYLOAD, date(2026, 9, 3))
    tx_low = transactions_from_detailed(cheap, date(2026, 9, 3))
    assert {t.transaction_id for t in tx_full}.isdisjoint({t.transaction_id for t in tx_low})


def test_activation_only_rows_are_skipped():
    payload = {**PAYLOAD, "results": [RETAIL_ROW]}
    day = date(2026, 9, 3)
    assert sales_from_detailed(payload, day) == []
    assert refunds_from_detailed(payload, day) == []
    assert transactions_from_detailed(payload, day) == []


def test_customer_price_from_cents_in_local_currency():
    sale = sales_from_detailed({**PAYLOAD, "results": [{**ROW, "sale_price": "1999", "currency": "RON"}]}, date(2026, 9, 3))[0]
    assert sale.customer_price == Decimal("19.99")
    assert sale.customer_currency == "RON"
    assert sale.extra["currency"] == "RON"


def test_line_item_type_accepts_int_and_string():
    day = date(2026, 9, 3)

    def kind(value, **more):
        return sales_from_detailed({**PAYLOAD, "results": [{**ROW, "line_item_type": value, **more}]}, day)[0].product_type

    assert kind(1) == AppStoreProductType.APP
    assert kind(2) == AppStoreProductType.DLC
    assert kind(3) == AppStoreProductType.IAP
    assert kind("Package") == AppStoreProductType.APP
    assert kind("DLC") == AppStoreProductType.DLC
    assert kind("In-Game Item") == AppStoreProductType.IAP
    assert kind("Something") == AppStoreProductType.OTHER
    assert kind("DLC", bundleid=9) == AppStoreProductType.APP
