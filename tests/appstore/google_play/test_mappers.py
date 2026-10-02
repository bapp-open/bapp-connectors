"""Maparile Google Play: earnings/sales/reviews CSV si API -> DTO-uri."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from bapp_connectors.core.dto import AppStoreProductType, FinancialTransactionType, SubscriptionStatus
from bapp_connectors.providers.appstore.google_play.mappers import (
    refund_from_voided,
    review_from_api,
    review_from_csv_row,
    sale_from_sales_row,
    subscription_from_v2,
    transactions_from_earnings_rows,
)

EARNINGS_BASE = {
    "Description": "GPA.3333-1111-2222-33333", "Transaction Date": "Sep 3, 2026", "Transaction Time": "10:15:00 PDT",
    "Tax Type": "", "Transaction Type": "Charge", "Refund Type": "", "Product Title": "BAPP Pro", "Package ID": "ro.cbsoft.app",
    "Product Type": "Subscription", "SKU ID": "pro_monthly", "Hardware": "Pixel 8", "Buyer Country": "RO", "Buyer State": "",
    "Buyer Postcode": "", "Buyer Currency": "RON", "Amount (Buyer Currency)": "29.99", "Currency Conversion Rate": "0.2010",
    "Merchant Currency": "EUR", "Amount (Merchant Currency)": "6.03", "Base Plan or Purchase Option ID": "monthly", "Offer ID": "",
    "Group ID": "", "First USD 1M Eligible": "Yes", "Service Fee %": "15", "Fee Description": "", "Promotion ID": "", "Sales Channel": "",
}


def test_earnings_charge_fee_tax_rows():
    rows = [
        EARNINGS_BASE,
        {**EARNINGS_BASE, "Transaction Type": "Google fee", "Amount (Merchant Currency)": "-0.90"},
        {**EARNINGS_BASE, "Transaction Type": "Tax", "Amount (Merchant Currency)": "-1.15"},
        {**EARNINGS_BASE, "Transaction Type": "Charge refund", "Amount (Merchant Currency)": "-6.03", "Refund Type": "Full"},
        {**EARNINGS_BASE, "Transaction Type": "Google fee refund", "Amount (Merchant Currency)": "0.90"},
    ]
    txs = transactions_from_earnings_rows(rows, 2026, 9)
    assert [t.transaction_type for t in txs] == [
        FinancialTransactionType.SALE, FinancialTransactionType.COMMISSION, FinancialTransactionType.DEDUCTION,
        FinancialTransactionType.RETURN, FinancialTransactionType.OTHER,
    ]
    assert txs[0].credit == Decimal("6.03") and txs[0].net_amount == Decimal("6.03")
    assert txs[1].debit == Decimal("0.90") and txs[1].net_amount == Decimal("-0.90")
    assert txs[1].commission_amount == Decimal("0.90")
    assert txs[3].net_amount == Decimal("-6.03")
    assert txs[4].credit == Decimal("0.90")
    assert {t.payout_id for t in txs} == {"202609:EUR"}
    assert txs[0].transaction_date.date() == date(2026, 9, 3)
    assert txs[0].order_id == "GPA.3333-1111-2222-33333"
    assert txs[0].extra["buyer_currency"] == "RON"
    assert txs[0].extra["conversion_rate"] == "0.2010"


def test_earnings_identical_rows_get_distinct_ids():
    txs = transactions_from_earnings_rows([EARNINGS_BASE, dict(EARNINGS_BASE)], 2026, 9)
    assert txs[0].transaction_id != txs[1].transaction_id
    again = transactions_from_earnings_rows([EARNINGS_BASE, dict(EARNINGS_BASE)], 2026, 9)
    assert [t.transaction_id for t in again] == [t.transaction_id for t in txs]


SALES_ROW = {
    "Order Number": "GPA.3333-1111-2222-33333", "Order Charged Date": "2026-09-03", "Order Charged Timestamp": "1788771300",
    "Financial Status": "Charged", "Device Model": "Pixel 8", "Product Title": "BAPP Pro", "Package ID": "ro.cbsoft.app",
    "Product Type": "subscription", "SKU ID": "pro_monthly", "Currency of Sale": "RON", "Item Price": "29.99",
    "Taxes Collected": "5.73", "Charged Amount": "29.99", "City of Buyer": "", "State of Buyer": "", "Postcode of Buyer": "",
    "Country of Buyer": "RO", "Base Plan or Purchase Option ID": "monthly", "Offer ID": "", "Group ID": "", "First USD 1M Eligible": "Yes",
    "Promotion ID": "", "Coupon Value": "", "Discount Rate": "", "Featured Products ID": "", "Price Experiment ID": "", "Sales Channel": "",
}


def test_sale_from_sales_row():
    sale = sale_from_sales_row(SALES_ROW, 2026, 9)
    assert sale.product_type == AppStoreProductType.SUBSCRIPTION
    assert sale.units == Decimal("1")
    assert sale.customer_price == Decimal("29.99")
    assert sale.customer_currency == "RON"
    assert sale.period_start == date(2026, 9, 3)
    assert sale.app_id == "ro.cbsoft.app"
    assert sale.is_refund is False
    refund = sale_from_sales_row({**SALES_ROW, "Financial Status": "Refund"}, 2026, 9)
    assert refund.is_refund is True and refund.units == Decimal("-1")
    assert sale_from_sales_row({**SALES_ROW, "Product Type": "paidapp"}, 2026, 9).product_type == AppStoreProductType.APP
    assert sale_from_sales_row({**SALES_ROW, "Product Type": "inapp"}, 2026, 9).product_type == AppStoreProductType.IAP


def test_review_from_csv_row_extracts_id_from_link():
    row = {
        "Package Name": "ro.cbsoft.app", "App Version Code": "210", "App Version Name": "2.1", "Reviewer Language": "ro", "Device": "Pixel 8",
        "Review Submit Date and Time": "2026-09-10T10:00:00Z", "Review Submit Millis Since Epoch": "1789120800000",
        "Review Last Update Date and Time": "2026-09-10T10:00:00Z", "Review Last Update Millis Since Epoch": "1789120800000",
        "Star Rating": "5", "Review Title": "", "Review Text": "Excelent", "Developer Reply Date and Time": "", "Developer Reply Millis Since Epoch": "",
        "Developer Reply Text": "", "Review Link": "https://play.google.com/console/developers/1/app/2/user-feedback/review-details?reviewId=gp%3AAOqpTOE&corpus=PUBLIC_REVIEWS",
    }
    review = review_from_csv_row(row, "ro.cbsoft.app")
    assert review.review_id == "gp:AOqpTOE"
    assert review.rating == 5
    assert review.language == "ro"
    assert review.created_at.year == 2026


def test_review_from_api_with_developer_comment():
    data = {
        "reviewId": "gp:AOqpTOE", "authorName": "Ion",
        "comments": [
            {"userComment": {"text": "\tBun", "lastModified": {"seconds": "1789120800"}, "starRating": 4, "reviewerLanguage": "ro", "appVersionName": "2.1"}},
            {"developerComment": {"text": "Mersi", "lastModified": {"seconds": "1789207200"}}},
        ],
    }
    review = review_from_api(data, "ro.cbsoft.app")
    assert review.body == "Bun"
    assert review.rating == 4
    assert review.developer_response == "Mersi"
    assert review.developer_response_at is not None


def test_refund_from_voided():
    refund = refund_from_voided({"purchaseToken": "tok", "orderId": "GPA.1", "purchaseTimeMillis": "1789120800000", "voidedTimeMillis": "1789207200000", "voidedSource": 0, "voidedReason": 1}, "ro.cbsoft.app")
    assert refund.refund_id == "GPA.1"
    assert refund.transaction_ref == "tok"
    assert refund.refunded_at.year == 2026
    assert refund.reason == "remorse"


def test_subscription_from_v2():
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "startTime": "2026-08-03T10:00:00Z",
        "lineItems": [{"productId": "pro_monthly", "expiryTime": "2026-10-03T10:00:00Z", "autoRenewingPlan": {"autoRenewEnabled": True}}],
        "latestOrderId": "GPA.1",
    }
    sub = subscription_from_v2(payload, "tok")
    assert sub.status == SubscriptionStatus.ACTIVE
    assert sub.price_id == "pro_monthly"
    assert sub.cancel_at_period_end is False
    assert sub.extra["purchase_token"] == "tok"
