"""Maparile Google Play: earnings/sales/reviews CSV si API -> DTO-uri."""

from __future__ import annotations

import base64
import json
from datetime import date
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import (
    AppStoreProductType,
    AppStoreStatMetric,
    FinancialTransactionType,
    SubscriptionStatus,
    WebhookEventType,
)
from bapp_connectors.providers.appstore.google_play.errors import GooglePlayWebhookError
from bapp_connectors.providers.appstore.google_play.mappers import (
    refund_from_voided,
    review_from_api,
    review_from_csv_row,
    sale_from_sales_row,
    stats_from_crashes_rows,
    stats_from_installs_rows,
    stats_from_ratings_rows,
    stats_from_store_rows,
    subscription_from_v2,
    transactions_from_earnings_rows,
    webhook_event_from_pubsub,
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


def _push(rtdn: dict, message_id: str = "m1") -> dict:
    return {"data": base64.b64encode(json.dumps(rtdn).encode()).decode(), "messageId": message_id}


def test_webhook_subscription_renewed():
    event = webhook_event_from_pubsub(_push({"packageName": "ro.cbsoft.app", "eventTimeMillis": "1789120800000", "subscriptionNotification": {"notificationType": 2, "purchaseToken": "tok", "subscriptionId": "pro_monthly"}}))
    assert event.event_type == WebhookEventType.SUBSCRIPTION_RENEWED
    assert event.payload == {"purchase_token": "tok", "product_id": "pro_monthly", "package_name": "ro.cbsoft.app"}
    assert event.idempotency_key == "m1" and event.event_id == "m1"
    unknown = webhook_event_from_pubsub(_push({"subscriptionNotification": {"notificationType": "abc"}}))
    assert unknown.event_type == WebhookEventType.UNKNOWN


def test_webhook_voided():
    event = webhook_event_from_pubsub(_push({"packageName": "ro.cbsoft.app", "voidedPurchaseNotification": {"purchaseToken": "tok", "orderId": "GPA.1", "productType": 1, "refundType": 1}}))
    assert event.event_type == WebhookEventType.PURCHASE_REFUNDED
    assert event.payload["order_id"] == "GPA.1"


def test_webhook_rejects_bad_base64_and_missing_message_id():
    with pytest.raises(GooglePlayWebhookError):
        webhook_event_from_pubsub({"data": "!!!not-base64", "messageId": "m1"})
    with pytest.raises(GooglePlayWebhookError):
        webhook_event_from_pubsub({"data": base64.b64encode(b"\xff\xfe").decode(), "messageId": "m1"})
    with pytest.raises(GooglePlayWebhookError):
        webhook_event_from_pubsub({"data": base64.b64encode(b"[1]").decode(), "messageId": "m1"})
    with pytest.raises(GooglePlayWebhookError, match="messageId"):
        webhook_event_from_pubsub(_push({"packageName": "x"}, message_id=""))


def test_earnings_real_headers():
    row = {
        "Description": "GPA.1", "Transaction Date": "Sep 3, 2026", "Transaction Time": "10:15:00 PDT", "Tax Type": "",
        "Transaction Type": "Charge", "Refund Type": "", "Product Title": "App", "Product id": "com.example.app",
        "Product Type": "subscription", "Sku Id": "private_vpn", "Hardware": "", "Buyer Country": "RO", "Buyer State": "",
        "Buyer Postal Code": "010101", "Buyer Currency": "RON", "Amount (Buyer Currency)": "10.00",
        "Currency Conversion Rate": "0.2", "Merchant Currency": "EUR", "Amount (Merchant Currency)": "2.00",
        "Base Plan ID": "monthly", "Offer ID": "", "Group ID": "", "First USD 1M Eligible": "Yes", "Service Fee %": "15",
        "Fee Description": "", "Promotion ID": "",
    }
    (tx,) = transactions_from_earnings_rows([row], 2026, 9)
    assert tx.extra["package_id"] == "com.example.app"
    assert tx.extra["sku"] == "private_vpn"
    assert tx.extra["base_plan"] == "monthly"
    assert tx.extra["postal_code"] == "010101"


def test_sales_real_headers():
    row = {
        "Order Number": "GPA.2", "Order Charged Date": "2026-09-03", "Order Charged Timestamp": "1", "Financial Status": "Charged",
        "Device Model": "", "Product Title": "App", "Product ID": "com.example.app", "Product Type": "subscription",
        "SKU ID": "private_vpn", "Currency of Sale": "RON", "Item Price": "10.00", "Taxes Collected": "0", "Charged Amount": "10.00",
        "City of Buyer": "", "State of Buyer": "", "Postal Code of Buyer": "010101", "Country of Buyer": "RO",
        "Base Plan ID": "monthly", "Offer ID": "", "Group ID": "", "First USD 1M Eligible": "Yes", "Promotion ID": "",
        "Coupon Value": "", "Discount Rate": "", "Featured Product ID": "feat1", "Price Experiment ID": "",
    }
    sale = sale_from_sales_row(row, 2026, 9)
    assert sale.app_id == "com.example.app"
    assert sale.sku == "private_vpn"
    assert sale.product_type == AppStoreProductType.SUBSCRIPTION
    assert sale.extra["base_plan"] == "monthly"
    assert sale.extra["postal_code"] == "010101"
    assert sale.extra["featured_product_id"] == "feat1"


INSTALLS_ROW = {
    "Date": "2026-09-01", "Package name": "ro.cbsoft.app", "Daily Device Installs": "12", "Daily Device Uninstalls": "3",
    "Daily Device Upgrades": "40", "Total User Installs": "900", "Daily User Installs": "11", "Daily User Uninstalls": "2",
    "Active Device Installs": "500", "Install events": "14", "Update events": "41", "Uninstall events": "4",
}


def test_stats_from_installs_overview_rows():
    stats = stats_from_installs_rows([INSTALLS_ROW], "ro.cbsoft.app", None)
    by_metric = {s.metric: s for s in stats}
    assert set(by_metric) == {AppStoreStatMetric.INSTALLS, AppStoreStatMetric.UNINSTALLS, AppStoreStatMetric.ACTIVE_DEVICES, AppStoreStatMetric.USER_INSTALLS}
    assert by_metric[AppStoreStatMetric.INSTALLS].value == Decimal("12")
    assert by_metric[AppStoreStatMetric.UNINSTALLS].value == Decimal("3")
    assert by_metric[AppStoreStatMetric.ACTIVE_DEVICES].value == Decimal("500")
    assert by_metric[AppStoreStatMetric.USER_INSTALLS].value == Decimal("11")
    first = by_metric[AppStoreStatMetric.INSTALLS]
    assert first.date == date(2026, 9, 1) and first.country == "" and first.app_id == "ro.cbsoft.app"
    assert first.extra == {
        "daily_device_upgrades": "40", "total_user_installs": "900", "daily_user_uninstalls": "2",
        "install_events": "14", "update_events": "41", "uninstall_events": "4",
    }
    assert len({s.external_key for s in stats}) == 4


def test_stats_from_installs_country_rows():
    row = {"Date": "2026-09-01", "Package Name": "ro.cbsoft.app", "Country": "RO", **{k: v for k, v in INSTALLS_ROW.items() if k not in {"Date", "Package name"}}}
    stats = stats_from_installs_rows([row, {**row, "Country": "DE"}], "ro.cbsoft.app", "Country")
    assert {s.country for s in stats} == {"RO", "DE"}
    assert len({s.external_key for s in stats}) == 8


def test_stats_from_ratings_rows_skips_blank():
    rows = [
        {"Date": "2026-09-01", "Package Name": "ro.cbsoft.app", "Daily Average Rating": "4.5", "Total Average Rating": "4.31"},
        {"Date": "2026-09-02", "Package name": "ro.cbsoft.app", "Daily Average Rating": "", "Total Average Rating": "4.31"},
    ]
    stats = stats_from_ratings_rows(rows, "ro.cbsoft.app")
    assert [(s.date.day, s.metric, s.value) for s in stats] == [
        (1, AppStoreStatMetric.RATING_DAILY, Decimal("4.5")),
        (1, AppStoreStatMetric.RATING_TOTAL, Decimal("4.31")),
        (2, AppStoreStatMetric.RATING_TOTAL, Decimal("4.31")),
    ]


def test_stats_from_crashes_rows():
    stats = stats_from_crashes_rows([{"Date": "2026-09-01", "Package Name": "ro.cbsoft.app", "Daily Crashes": "2", "Daily ANRs": "1"}], "ro.cbsoft.app")
    assert {s.metric: s.value for s in stats} == {AppStoreStatMetric.CRASHES: Decimal("2"), AppStoreStatMetric.ANRS: Decimal("1")}


def test_stats_from_store_rows_by_traffic_source_and_country():
    traffic = [
        {"Date": "2026-09-01", "Package name": "ro.cbsoft.app", "Traffic source": "Google Search", "Total store acquisitions": "7"},
        {"Date": "2026-09-01", "Package name": "ro.cbsoft.app", "Traffic source": "Third-party referrals", "Total store acquisitions": "2"},
    ]
    stats = stats_from_store_rows(traffic, "ro.cbsoft.app", "traffic_source")
    assert [(s.country, s.extra["traffic_source"], s.value) for s in stats] == [("", "Google Search", Decimal("7")), ("", "Third-party referrals", Decimal("2"))]
    assert len({s.external_key for s in stats}) == 2
    by_country = stats_from_store_rows([{"Date": "2026-09-01", "Package Name": "ro.cbsoft.app", "Country": "RO", "Total store acquisitions": "5"}], "ro.cbsoft.app", "country")
    assert by_country[0].country == "RO" and by_country[0].extra == {} and by_country[0].metric == AppStoreStatMetric.STORE_ACQUISITIONS
    missing = stats_from_store_rows([{"Date": "2026-09-01", "Total store acquisitions": "5"}], "ro.cbsoft.app", "country")
    assert missing[0].country == ""
