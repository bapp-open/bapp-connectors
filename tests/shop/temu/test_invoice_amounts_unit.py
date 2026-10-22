from decimal import Decimal

import pytest

from bapp_connectors.core.errors import AuthenticationError
from bapp_connectors.providers.shop.temu.adapter import TemuShopAdapter
from bapp_connectors.providers.shop.temu.mappers import amounts_from_invoice_detail, amounts_from_v2, money
from tests.shop.temu.conftest import CREDS, err, ok
from tests.shop.temu.test_orders_unit import load


def _adapter(fake):
    return TemuShopAdapter(CREDS, http_client=fake, config={})


def test_attach_invoice_payload(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", ok({"success": True}))
    assert adapter.attach_invoice("PO-1", "https://portal.example.test/f/abc?format=file", name="FAC 2026 17") is True
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "temu.pay.tax.merchant.upload.invoice" and fake.last_call().kwargs.get("retry") is False
    assert body["parentOrderSn"] == "PO-1" and body["invoiceDirection"] == 1 and body["recipientType"] == 1
    assert body["invoiceName"] == "FAC 2026 17" and body["fileUrl"].startswith("https://")
    assert "invoiceCurrency" not in body and "invoiceAmount" not in body


def test_attach_invoice_name_defaults_to_url_basename(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", ok({"success": True}))
    adapter.attach_invoice("PO-1", "https://x.example.test/docs/FAC-2026-18.pdf?format=file")
    assert fake.last_call().kwargs["json"]["invoiceName"] == "FAC-2026-18"


def test_attach_credit_note_with_optional_fields(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", ok({"success": True}))
    adapter.attach_invoice("PO-1", "https://x.example.test/s.pdf", credit_note=True, currency="RON", date="2026-10-22",
                           amount=Decimal("124.95"))
    body = fake.last_call().kwargs["json"]
    assert body["invoiceDirection"] == 2 and body["invoiceCurrency"] == "RON" and body["invoiceDate"] == "2026-10-22"
    assert body["invoiceAmount"] == 124.95


def test_money_helper():
    assert money({"currency": "RON", "amount": 59.5}) == Decimal("59.50")
    assert money({"amount": "1"}) == Decimal("1.00") and money(None) == Decimal("0") and money({}) == Decimal("0")


def test_amounts_from_v2_fixture():
    oa = amounts_from_v2(load("amount_v2.json"), "PO-167-1000000000000000")
    assert oa.source == "amount_query" and oa.currency == "RON" and oa.order_id == "PO-167-1000000000000000"
    [line] = oa.lines
    assert line.item_id == "167-2000000000000001" and line.quantity == Decimal("2")
    assert line.unit_price_incl_vat == Decimal("59.50") and line.unit_price_excl_vat == Decimal("50.00")
    assert line.vat_rate == Decimal("19") and line.line_total_incl_vat == Decimal("119.00")
    assert line.base_price_total == Decimal("78.00") and line.discount_seller == Decimal("5.00") and line.discount_platform == Decimal("0.00")
    assert line.estimated_settlement == Decimal("90.00")
    assert oa.shipping_excl_vat == Decimal("10.00") and oa.shipping_incl_vat == Decimal("11.90")
    assert oa.tax_total == Decimal("19.95") and oa.customer_paid_total == Decimal("124.95")
    assert oa.estimated_revenue == Decimal("90.00") and oa.estimated_revenue_deduction == Decimal("6.05")
    assert oa.refunds_total == Decimal("0.00")


def test_amounts_from_v2_derives_incl_price_when_missing():
    data = load("amount_v2.json")
    del data["orderList"][0]["unitRetailPriceTaxIncl"]
    assert amounts_from_v2(data, "PO-1").lines[0].unit_price_incl_vat == Decimal("59.50")


def test_amounts_from_invoice_detail_fixture():
    oa = amounts_from_invoice_detail(load("invoice_detail.json"), "PO-167-1000000000000000")
    assert oa.source == "invoice_detail" and oa.currency == "RON"
    [line] = oa.lines
    assert line.item_id == "167-2000000000000001" and line.quantity == Decimal("2") and line.vat_rate == Decimal("19")
    assert line.unit_price_incl_vat == Decimal("56.53") and line.unit_price_excl_vat == Decimal("47.50")
    assert line.line_total_incl_vat == Decimal("113.05")
    assert oa.shipping_incl_vat == Decimal("11.90") and oa.shipping_excl_vat == Decimal("10.00")
    assert oa.customer_paid_total == Decimal("124.95") and oa.estimated_revenue == Decimal("0") and oa.estimated_revenue_deduction == Decimal("0")


def test_get_order_amounts_prefers_v2(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", ok(load("amount_v2.json")))
    oa = adapter.get_order_amounts("PO-167-1000000000000000")
    assert oa.source == "amount_query" and fake.last_call().kwargs["json"]["type"] == "temu.order.amount.v2.query"


def test_amounts_fall_back_to_invoice_detail_on_missing_scope(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", lambda m, p, kw: err(3000032, "no access") if kw["json"]["type"] == "temu.order.amount.v2.query"
             else ok(load("invoice_detail.json")))
    oa = adapter.get_order_amounts("PO-1")
    assert oa.source == "invoice_detail" and oa.lines[0].unit_price_incl_vat > 0


def test_amounts_reraise_when_both_unavailable(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", lambda m, p, kw: err(3000032, "no access") if kw["json"]["type"] == "temu.order.amount.v2.query"
             else ok({"invoiceDetailInfoList": None}))
    with pytest.raises(AuthenticationError):
        adapter.get_order_amounts("PO-1")


def test_get_order_uses_amounts_for_line_prices(fake):
    adapter = _adapter(fake)
    detail = load("order_detail.json")
    amounts = load("amount_v2.json")
    amounts["orderList"][0]["orderSn"] = detail["orderList"][0]["orderSn"]

    def route(m, p, kw):
        t = kw["json"]["type"]
        return {"bg.order.detail.v2.get": ok(detail), "bg.order.shippinginfo.v2.get": ok(load("shipping_info.json")),
                "temu.order.amount.v2.query": ok(amounts)}[t]

    fake.add("POST", "openapi/router", route)
    o = adapter.get_order(detail["parentOrderMap"]["parentOrderSn"])
    # host convention (shop_orders.intake._line_prices): unit_price is NET, extra["subtotal"] the exact gross line total
    assert o.extra["amounts_missing"] is False and o.items[0].unit_price == Decimal("50.00") and o.items[0].tax_rate == Decimal("19")
    assert o.items[0].extra["subtotal"] == "119.00" and o.items[0].extra["unit_price_incl_vat"] == "59.50"
    assert o.total == Decimal("124.95") and o.extra["amounts"]["estimated_revenue"] == "90.00"


def test_amounts_line_with_zero_quantity_stays_zero():
    data = load("amount_v2.json")
    data["orderList"][0]["quantity"] = 0
    assert amounts_from_v2(data, "PO-1").lines[0].quantity == Decimal("0")
