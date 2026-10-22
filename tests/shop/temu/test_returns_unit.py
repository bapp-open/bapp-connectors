import datetime
from decimal import Decimal

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.core.dto.returns import ReturnKind, ReturnReason
from bapp_connectors.providers.shop.temu.adapter import TemuShopAdapter
from bapp_connectors.providers.shop.temu.manifest import manifest
from bapp_connectors.providers.shop.temu.mappers import return_from_aftersales
from tests.shop.temu.conftest import CREDS, err, ok
from tests.shop.temu.test_orders_unit import load

SINCE = datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC)
UNTIL = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)


def test_declares_capability():
    assert ReturnsCapability in manifest.capabilities


def test_maps_refunded_request_with_detail():
    rows = load("aftersales_list.json")["data"]
    detail = load("aftersales_detail.json")
    r = return_from_aftersales(rows[0], detail)
    assert r.external_id == rows[0]["parentAfterSalesSn"] and r.external_order_id == rows[0]["parentOrderSn"]
    assert r.status_raw == "5" and r.status_label == "refunded" and r.kind == ReturnKind.REFUND
    assert r.requested_at == datetime.datetime.fromtimestamp(1792323496, tz=datetime.UTC) and r.requested_at.tzinfo is not None
    assert r.refund is not None and r.refund.amount == Decimal("59.50") and r.refund.currency == "RON" and r.refund.status == "refunded"
    [line] = r.lines
    assert line.external_line_id == detail["afterSalesList"][0]["afterSalesSn"] and line.sku == "TEST11"
    assert line.quantity == Decimal("1") and line.unit_price == Decimal("59.50")
    assert line.reason_code == "24" and line.reason_label == "Damaged item" and line.reason == ReturnReason.DAMAGED
    assert line.customer_note == "ambalaj rupt" and r.comment == "ambalaj rupt"
    assert r.raw["detail"]["parentAfterSalesStatus"] == 5 and r.customer_name == ""


def test_kind_follows_status():
    rows = load("aftersales_list.json")["data"]
    assert return_from_aftersales(rows[1], None).kind == ReturnKind.RETURN  # 2 = return parcel shipped
    assert return_from_aftersales(rows[2], None).kind == ReturnKind.RETURN  # 10 = return requested
    assert return_from_aftersales(rows[0], None).kind == ReturnKind.REFUND  # 5 = refunded, no parcel seen
    r = return_from_aftersales({**rows[0], "parentAfterSalesStatus": 99}, None)
    assert r.status_raw == "99" and r.status_label == "" and r.kind == ReturnKind.REFUND


def test_reason_map_defaults_to_other():
    detail = load("aftersales_detail.json")
    detail["afterSalesList"][0]["afterSalesReasonCode"] = 9999
    assert return_from_aftersales(load("aftersales_list.json")["data"][0], detail).lines[0].reason == ReturnReason.OTHER


def test_get_returns_pages_with_seconds_window_and_detail(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    listing = load("aftersales_list.json")
    detail = load("aftersales_detail.json")

    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        if t == "bg.aftersales.parentaftersales.list.get":
            return ok(listing)
        if t == "temu.aftersales.parentaftersales.detail.get":
            sn = kwargs["json"]["parentAfterSalesSn"]
            if sn.endswith("12-D02"):
                return err(7000000, "BUSINESS_SERVICE_ERROR")
            return ok({**detail, "parentAfterSalesSn": sn})
        raise AssertionError(t)

    fake.add("POST", "openapi/router", route)
    returns = adapter.get_returns(SINCE, UNTIL)
    assert [r.external_id for r in returns] == [row["parentAfterSalesSn"] for row in listing["data"]]
    body = fake.calls[0].kwargs["json"]
    assert body["createAtStart"] == int(SINCE.timestamp()) and body["createAtEnd"] == int(UNTIL.timestamp())
    assert body["pageNo"] == 1 and body["pageSize"] == 50
    assert returns[0].lines and returns[2].lines == [] and returns[2].raw.get("detail_error")  # failing detail keeps the row
    assert adapter.resolve_return_awb("ABC") == "ABC"


def test_get_returns_follows_total_across_pages(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    listing = load("aftersales_list.json")
    listing["total"] = 120

    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        if t == "bg.aftersales.parentaftersales.list.get":
            page = kwargs["json"]["pageNo"]
            rows = [{**r, "parentAfterSalesSn": f"{r['parentAfterSalesSn']}-{page}"} for r in listing["data"]] if page <= 2 else []
            return ok({**listing, "data": rows})
        return ok({"afterSalesList": []})

    fake.add("POST", "openapi/router", route)
    returns = adapter.get_returns(SINCE, UNTIL)
    assert len(returns) == 6 and [c.kwargs["json"]["pageNo"] for c in fake.calls if c.kwargs["json"]["type"].endswith("list.get")] == [1, 2, 3]
