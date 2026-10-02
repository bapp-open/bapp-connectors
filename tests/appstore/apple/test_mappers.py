"""Maparile Apple: randuri SALES / FINANCE_DETAIL -> DTO-uri."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from bapp_connectors.core.dto import AppStoreProductType, FinancialTransactionType
from bapp_connectors.providers.appstore.apple.mappers import (
    refund_from_sale,
    review_from_apple,
    sale_from_sales_row,
    transaction_from_finance_row,
)

SALES_ROW = {
    "Provider": "APPLE", "Provider Country": "US", "SKU": "ro.cbsoft.pro.monthly", "Developer": "CBSoft",
    "Title": "BAPP Pro", "Version": "2.1", "Product Type Identifier": "IAY", "Units": "3",
    "Developer Proceeds": "4.26", "Begin Date": "09/01/2026", "End Date": "09/01/2026",
    "Customer Currency": "EUR", "Country Code": "RO", "Currency of Proceeds": "EUR",
    "Apple Identifier": "6450000000", "Customer Price": "5.99", "Promo Code": "", "Parent Identifier": "ro.cbsoft.app",
    "Subscription": "Renewal", "Period": "1 Month", "Category": "Business", "CMB": "", "Device": "iPhone",
    "Supported Platforms": "iOS", "Proceeds Reason": "", "Preserved Pricing": "", "Client": "", "Order Type": "",
}


def test_sale_from_subscription_renewal_row():
    sale = sale_from_sales_row(SALES_ROW, date(2026, 9, 1))
    assert sale.product_type == AppStoreProductType.SUBSCRIPTION_RENEWAL
    assert sale.units == Decimal("3")
    assert sale.proceeds_unit == Decimal("4.26")
    assert sale.proceeds_total == Decimal("12.78")
    assert sale.customer_price == Decimal("5.99")
    assert sale.country == "RO"
    assert sale.app_id == "6450000000"
    assert sale.period_start == date(2026, 9, 1)
    assert sale.is_refund is False
    assert sale.extra["product_type_identifier"] == "IAY"
    assert sale.provider_meta.provider == "apple"


def test_sale_new_subscription_and_app_types():
    assert sale_from_sales_row({**SALES_ROW, "Subscription": "New"}, date(2026, 9, 1)).product_type == AppStoreProductType.SUBSCRIPTION_NEW
    assert sale_from_sales_row({**SALES_ROW, "Product Type Identifier": "1F"}, date(2026, 9, 1)).product_type == AppStoreProductType.APP
    assert sale_from_sales_row({**SALES_ROW, "Product Type Identifier": "IA1"}, date(2026, 9, 1)).product_type == AppStoreProductType.IAP
    assert sale_from_sales_row({**SALES_ROW, "Product Type Identifier": "1-B"}, date(2026, 9, 1)).product_type == AppStoreProductType.APP


def test_updates_and_redownloads_are_skipped():
    assert sale_from_sales_row({**SALES_ROW, "Product Type Identifier": "7F"}, date(2026, 9, 1)) is None
    assert sale_from_sales_row({**SALES_ROW, "Product Type Identifier": "3"}, date(2026, 9, 1)) is None


def test_negative_units_is_refund_and_maps_to_refund_dto():
    sale = sale_from_sales_row({**SALES_ROW, "Units": "-1", "Customer Price": "-5.99"}, date(2026, 9, 1))
    assert sale.is_refund is True
    assert sale.proceeds_total == Decimal("-4.26")
    refund = refund_from_sale(sale)
    assert refund.amount == Decimal("5.99")
    assert refund.currency == "EUR"
    assert refund.refund_id == sale.external_key


def test_sales_row_with_blank_amounts():
    sale = sale_from_sales_row({**SALES_ROW, "Product Type Identifier": "1F", "Developer Proceeds": "", "Customer Price": ""}, date(2026, 9, 1))
    assert sale.proceeds_unit == Decimal("0")
    assert sale.customer_price == Decimal("0")


def test_external_key_is_stable():
    a = sale_from_sales_row(SALES_ROW, date(2026, 9, 1))
    b = sale_from_sales_row(dict(SALES_ROW), date(2026, 9, 1))
    assert a.external_key == b.external_key


FINANCE_ROW = {
    "Vendor Name": "CBSoft", "Start Date": "08/30/2026", "End Date": "09/26/2026", "Transaction Date": "09/03/2026",
    "Settlement Date": "09/26/2026", "Apple Identifier": "6450000000", "SKU": "ro.cbsoft.pro.monthly", "Title": "BAPP Pro",
    "Developer Name": "CBSoft", "Product Type Identifier": "IAY", "Country of Sale": "RO", "Quantity": "3",
    "Partner Share": "4.26", "Extended Partner Share": "12.78", "Partner Share Currency": "EUR",
    "Customer Price": "5.99", "Customer Currency": "EUR", "Sale or Return": "S", "Promo Code": "", "Order Type": "", "Region": "",
}


def test_finance_sale_row():
    tx = transaction_from_finance_row(FINANCE_ROW, "2026-09")
    assert tx.transaction_type == FinancialTransactionType.SALE
    assert tx.credit == Decimal("12.78")
    assert tx.debit == Decimal("0")
    assert tx.net_amount == Decimal("12.78")
    assert tx.currency == "EUR"
    assert tx.payout_id == "2026-09:EUR"
    assert tx.transaction_date.date() == date(2026, 9, 3)
    assert tx.payment_date.date() == date(2026, 10, 29)
    assert tx.extra["units"] == 3
    assert tx.extra["fiscal_period"] == "2026-09"


def test_finance_return_row_is_negative():
    tx = transaction_from_finance_row({**FINANCE_ROW, "Quantity": "-1", "Extended Partner Share": "-4.26", "Sale or Return": "R"}, "2026-09")
    assert tx.transaction_type == FinancialTransactionType.RETURN
    assert tx.debit == Decimal("4.26")
    assert tx.net_amount == Decimal("-4.26")


def test_review_from_apple_with_response():
    data = {
        "id": "rev1",
        "attributes": {"rating": 4, "title": "Bun", "body": "Merge", "reviewerNickname": "Ion", "createdDate": "2026-09-10T10:00:00-07:00", "territory": "ROU"},
        "relationships": {"response": {"data": {"type": "customerReviewResponses", "id": "resp1"}}},
    }
    responses = {"resp1": {"attributes": {"responseBody": "Multumim", "lastModifiedDate": "2026-09-11T08:00:00Z"}}}
    review = review_from_apple(data, responses, app_id="645")
    assert review.rating == 4
    assert review.country == "ROU"
    assert review.developer_response == "Multumim"
    assert review.developer_response_at is not None
    assert review.app_id == "645"
