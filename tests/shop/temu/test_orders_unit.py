import datetime
import json
import pathlib
from decimal import Decimal

from bapp_connectors.core.dto.order import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.providers.shop.temu.adapter import TemuShopAdapter
from bapp_connectors.providers.shop.temu.mappers import contact_from_shipping_info, country_from_region, order_from_temu
from tests.shop.temu.conftest import CREDS, ok

FIX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


def test_order_without_amounts_is_flagged():
    parent = load("order_detail.json")
    o = order_from_temu(parent, load("shipping_info.json"), "RON", None)
    assert o.order_id == o.external_id == parent["parentOrderMap"]["parentOrderSn"]
    assert o.status == OrderStatus.SHIPPED and o.raw_status == "4"
    assert o.payment_status == PaymentStatus.PAID and o.payment_type == PaymentType.ONLINE_CARD
    assert o.currency == "RON"
    assert o.items[0].unit_price == Decimal("0") and o.extra["amounts_missing"] is True
    assert o.items[0].sku == "TEST11" and o.items[0].item_id.startswith("167-")
    assert o.items[0].product_id == str(parent["orderList"][0]["goodsId"]) and o.items[0].quantity == Decimal("1")
    assert o.items[0].extra["skuId"] == parent["orderList"][0]["skuId"] and o.items[0].extra["packageSn"].startswith("PK-")
    assert o.shipping.email == "" and o.extra["relay_email"].endswith("temuemail.com")
    assert o.shipping.name == "Client Test" and o.shipping.phone and o.shipping.address.country == "RO"
    assert o.shipping.address.city == "Oraș Test" and o.shipping.address.postal_code == "400000"
    assert o.created_at.tzinfo is not None and o.updated_at is not None
    assert o.provider_meta.provider == "temu" and o.provider_meta.raw_id == o.order_id
    assert o.extra["site_id"] == 140 and o.extra["fulfillment_type"] == "fulfillBySeller"


def test_status_map_covers_verified_codes():
    for code, expected in ((1, OrderStatus.PENDING), (2, OrderStatus.PROCESSING), (3, OrderStatus.CANCELLED),
                           (4, OrderStatus.SHIPPED), (5, OrderStatus.DELIVERED), (99, OrderStatus.PENDING)):
        parent = load("order_detail.json")
        parent["parentOrderMap"]["parentOrderStatus"] = code
        assert order_from_temu(parent, None, "RON").status == expected


def test_order_without_shipping_info_has_no_contact():
    o = order_from_temu(load("order_detail.json"), None, "RON")
    assert o.shipping is None and o.shipping_address is None


def test_country_from_region():
    assert country_from_region("Romania") == "RO" and country_from_region("GERMANY") == "DE"
    assert country_from_region("Atlantis") == "" and country_from_region(None) == ""


def test_contact_from_shipping_info_keeps_relay_email_out():
    c = contact_from_shipping_info(load("shipping_info.json"))
    assert c.email == "" and c.extra["relay_email"].endswith("temuemail.com") and c.address.street == "Strada Exemplu 1, Ap. 2"


def test_get_orders_paginates_by_page_number(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    page = load("order_list.json")
    page["totalItemNum"] = 120
    fake.add("POST", "openapi/router", ok(page))
    since = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    res = adapter.get_orders(since=since, cursor="2")
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.order.list.v2.get" and body["pageNumber"] == 2 and body["pageSize"] == 50
    assert body["parentOrderStatus"] == 0 and body["updateAtStart"] == int(since.timestamp())
    assert res.cursor == "3" and res.has_more and res.total == 120
    assert len(res.items) == 3 and res.items[0].provider_meta.provider == "temu"
    assert res.items[0].extra["amounts_missing"] is True and res.items[0].shipping is None
    assert len(fake.calls) == 1  # the list pass makes no per-order calls


def test_get_orders_last_page(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    page = load("order_list.json")
    page["totalItemNum"] = 3
    fake.add("POST", "openapi/router", ok(page))
    res = adapter.get_orders()
    assert res.cursor is None and res.has_more is False and fake.last_call().kwargs["json"]["pageNumber"] == 1


def test_get_order_combines_detail_shipping_and_amounts(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    detail = load("order_detail.json")

    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        if t == "bg.order.detail.v2.get":
            return ok(detail)
        if t == "bg.order.shippinginfo.v2.get":
            return ok(load("shipping_info.json"))
        if t == "temu.order.amount.v2.query":
            return {"success": False, "errorCode": 3000032, "errorMsg": "no scope", "requestId": "r"}
        if t == "temu.pay.tax.invoice.detail.query":
            return ok({"invoiceDetailInfoList": None})
        raise AssertionError(t)

    fake.add("POST", "openapi/router", route)
    o = adapter.get_order(detail["parentOrderMap"]["parentOrderSn"])
    assert o.shipping.name == "Client Test" and o.extra["amounts_missing"] is True
    assert fake.calls[0].kwargs["json"]["parentOrderSn"] == o.order_id


def test_get_customer_details_uses_decrypt_api(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    fake.add("POST", "openapi/router", ok(load("shipping_info.json")))
    c = adapter.get_customer_details("PO-167-1")
    assert fake.last_call().kwargs["json"]["type"] == "bg.order.decryptshippinginfo.get"
    assert c.name == "Client Test" and c.email == "" and c.address.country == "RO"


def test_find_order_by_reference(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    assert adapter.find_order_by_reference("167-2000000000000001") is None
    detail = load("order_detail.json")
    fake.add("POST", "openapi/router", lambda m, p, kw: ok(detail) if kw["json"]["type"] == "bg.order.detail.v2.get"
             else ok(load("shipping_info.json")) if kw["json"]["type"] == "bg.order.shippinginfo.v2.get"
             else {"success": False, "errorCode": 3000032, "errorMsg": "x", "requestId": "r"} if kw["json"]["type"] == "temu.order.amount.v2.query"
             else ok({"invoiceDetailInfoList": None}))
    assert adapter.find_order_by_reference(detail["parentOrderMap"]["parentOrderSn"]).order_id == detail["parentOrderMap"]["parentOrderSn"]
