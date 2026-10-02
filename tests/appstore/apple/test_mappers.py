"""Maparile Apple: randuri SALES / FINANCE_DETAIL -> DTO-uri."""

from __future__ import annotations

from datetime import UTC, date
from decimal import Decimal

from bapp_connectors.core.dto import AppStoreProductType, FinancialTransactionType, SubscriptionStatus
from bapp_connectors.providers.appstore.apple.mappers import (
    app_from_apple,
    parse_apple_date,
    parse_iso_datetime,
    refund_from_sale,
    review_from_apple,
    sale_from_sales_row,
    stats_from_sales_rows,
    subscription_from_server_status,
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


def test_external_key_discriminates_version_and_sign():
    base = sale_from_sales_row(SALES_ROW, date(2026, 9, 1))
    other_version = sale_from_sales_row({**SALES_ROW, "Version": "2.2"}, date(2026, 9, 1))
    refund = sale_from_sales_row({**SALES_ROW, "Units": "-1"}, date(2026, 9, 1))
    assert base.external_key != other_version.external_key
    assert base.external_key != refund.external_key
    # valoarea Units nu intra in cheie, doar semnul
    assert base.external_key == sale_from_sales_row({**SALES_ROW, "Units": "7"}, date(2026, 9, 1)).external_key


def test_refund_reason_comes_from_extra():
    sale = sale_from_sales_row({**SALES_ROW, "Units": "-1", "Proceeds Reason": "Rate Before Tax"}, date(2026, 9, 1))
    assert sale.extra["version"] == "2.1"
    assert refund_from_sale(sale).reason == "Rate Before Tax"


def test_subscription_from_server_status():
    tx = {"originalTransactionId": "1000", "productId": "pro.monthly", "price": 5990, "currency": "EUR",
          "expiresDate": 1788000000000, "originalPurchaseDate": 1785000000000, "environment": "Production", "bundleId": "ro.cbsoft"}
    sub = subscription_from_server_status(1, tx, {"autoRenewStatus": 0, "autoRenewProductId": "pro.yearly"})
    assert sub.status == SubscriptionStatus.ACTIVE
    assert sub.amount == Decimal("5.99")
    assert sub.current_period_end.utcoffset() == UTC.utcoffset(None)
    assert sub.current_period_end.timestamp() == 1788000000
    assert sub.cancel_at_period_end is True
    assert sub.extra["original_transaction_id"] == "1000"
    assert subscription_from_server_status(2, tx, {}).status == SubscriptionStatus.CANCELLED
    assert subscription_from_server_status(99, tx, {}).status == SubscriptionStatus.PENDING
    assert subscription_from_server_status(1, tx, {"autoRenewStatus": 1}).cancel_at_period_end is False


def test_app_from_apple():
    app = app_from_apple({"id": 645, "attributes": {"name": "BAPP", "bundleId": "ro.cbsoft.app", "sku": "SKU1"}})
    assert (app.app_id, app.name, app.bundle_id, app.extra["sku"]) == ("645", "BAPP", "ro.cbsoft.app", "SKU1")


def test_review_without_response():
    attrs = {"rating": 5, "createdDate": "2026-09-10T10:00:00-07:00"}
    for data in (
        {"id": "r1", "attributes": attrs, "relationships": {"response": {"data": None}}},
        {"id": "r2", "attributes": attrs},
    ):
        review = review_from_apple(data, {}, app_id="645")
        assert review.developer_response == ""
        assert review.developer_response_at is None
        assert review.rating == 5


def test_parsers():
    assert parse_apple_date("09/03/2026") == date(2026, 9, 3)
    parsed = parse_iso_datetime("2026-09-11T08:00:00Z")
    assert parsed.tzinfo is not None
    assert parse_iso_datetime(None) is None


def test_finance_row_falls_back_to_preamble_start_date():
    row = {"Extended Partner Share": "5.00", "Partner Share Currency": "EUR", "Sale or Return": "S", "Quantity": "1"}
    preamble = {"Start Date": "09/29/2024", "End Date": "11/02/2024"}
    tx = transaction_from_finance_row(row, "2024-10", preamble)
    assert tx.transaction_date.date().isoformat() == "2024-09-29"
    assert tx.extra["period_start"] == "2024-09-29"
    assert tx.extra["period_end"] == "2024-11-02"
    assert transaction_from_finance_row(row, "2024-10").extra["period_start"] == ""


def _stat_row(identifier, units, country="RO", app="645"):
    return {"Apple Identifier": app, "Product Type Identifier": identifier, "Units": units, "Country Code": country}


def test_stats_from_sales_rows():
    rows = [
        _stat_row("1F", "2"),
        _stat_row("1", "3"),
        _stat_row("1F", "4", country="DE"),
        _stat_row("7F", "10"),
        _stat_row("3", "1"),
        _stat_row("1F", "99", app="999"),  # alta aplicatie
        _stat_row("1F", "-5"),  # unitati negative: nu sunt descarcari
        _stat_row("IAY", "7"),  # nu e tip de aplicatie
    ]
    stats = stats_from_sales_rows(rows, date(2026, 9, 1), "645")
    by_key = {(s.metric.value, s.country): s.value for s in stats}
    assert by_key == {
        ("downloads", "DE"): Decimal("4"),
        ("downloads", "RO"): Decimal("5"),
        ("downloads", ""): Decimal("9"),
        ("updates", "RO"): Decimal("10"),
        ("updates", ""): Decimal("10"),
        ("redownloads", "RO"): Decimal("1"),
        ("redownloads", ""): Decimal("1"),
    }
    total = next(s for s in stats if s.metric.value == "downloads" and s.country == "")
    assert total.extra == {"product_type_identifiers": ["1", "1F"]}
    assert total.date == date(2026, 9, 1) and total.app_id == "645"
    assert len({s.external_key for s in stats}) == len(stats)
