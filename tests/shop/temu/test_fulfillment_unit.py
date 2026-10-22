from bapp_connectors.core.capabilities import ShippingService
from bapp_connectors.providers.shop.temu.adapter import LABEL_DOCUMENT_TYPE, TemuShopAdapter
from tests.shop.temu.conftest import CREDS, ok
from tests.shop.temu.test_orders_unit import load

SERVICES = {"onlineChannelDtoList": [
    {"channelId": 7, "shipCompanyId": 3, "shippingCompanyName": "Curier Rapid", "estimatedText": "12.50 RON",
     "estimatedCurrencyCode": "RON", "shipLogisticsType": "LOCAL"},
    {"channelId": 8, "shipCompanyId": 4, "shippingCompanyName": "Curier Lent", "estimatedCurrencyCode": "RON"},
], "unavailableChannelDtoList": [{"channelId": 9, "unavailableReason": "zona"}]}


def _adapter(fake, **config):
    return TemuShopAdapter(CREDS, http_client=fake, config=config)


def _router(detail, extra=None):
    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        if t == "bg.order.detail.v2.get":
            return ok(detail)
        if extra and t in extra:
            value = extra[t]
            return value(kwargs["json"]) if callable(value) else ok(value)
        return ok({})
    return route


def test_list_carriers_maps_provider_fields(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", ok([{"logisticsServiceProviderId": 699272611, "logisticsServiceProviderName": "Curier X",
                                            "logisticsBrandName": "X"}]))
    [carrier] = adapter.list_carriers()
    assert carrier.carrier_id == "699272611" and carrier.name == "Curier X" and carrier.extra["logisticsBrandName"] == "X"
    assert fake.last_call().kwargs["json"]["type"] == "bg.logistics.companies.get"


def test_confirm_shipment_builds_send_request(fake):
    adapter = _adapter(fake)
    detail = load("order_detail.json")
    fake.add("POST", "openapi/router", _router(detail))
    adapter.confirm_shipment(detail["parentOrderMap"]["parentOrderSn"], "AWB123", "699272611")
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.logistics.shipment.v2.confirm" and body["sendType"] == 0 and body.get("retry") is None
    [req] = body["sendRequestList"]
    assert req["trackingNumber"] == "AWB123" and req["carrierId"] == "699272611"
    line = detail["orderList"][0]
    assert len(req["orderSendInfoList"]) == len(detail["orderList"])
    assert req["orderSendInfoList"][0] == {"orderSn": line["orderSn"], "parentOrderSn": detail["parentOrderMap"]["parentOrderSn"],
                                           "goodsId": line["goodsId"], "skuId": line["skuId"], "quantity": line["quantity"]}


def test_confirm_shipment_can_target_some_lines(fake):
    adapter = _adapter(fake)
    detail = load("order_detail.json")
    detail["orderList"].append({**detail["orderList"][0], "orderSn": "167-2000000000000009", "quantity": 2})
    fake.add("POST", "openapi/router", _router(detail))
    adapter.confirm_shipment(detail["parentOrderMap"]["parentOrderSn"], "AWB1", "1", items=["167-2000000000000009"])
    [req] = fake.last_call().kwargs["json"]["sendRequestList"]
    assert [i["orderSn"] for i in req["orderSendInfoList"]] == ["167-2000000000000009"] and req["orderSendInfoList"][0]["quantity"] == 2


def test_list_shipping_services(fake):
    adapter = _adapter(fake)
    detail = load("order_detail.json")
    fake.add("POST", "openapi/router", _router(detail, {"bg.logistics.shippingservices.get": SERVICES}))
    services = adapter.list_shipping_services(detail["parentOrderMap"]["parentOrderSn"], "WH-1")
    body = fake.last_call().kwargs["json"]
    assert body["warehouseId"] == "WH-1" and body["shipOrderInfoList"][0]["orderSn"] == detail["orderList"][0]["orderSn"]
    assert [s.service_id for s in services] == ["7", "8"] and services[0].carrier_id == "3" and services[0].name == "Curier Rapid"
    assert services[0].currency == "RON" and services[0].extra["estimatedText"] == "12.50 RON"


def test_create_shipment_returns_package_sn(fake):
    adapter = _adapter(fake)
    detail = load("order_detail.json")
    fake.add("POST", "openapi/router", _router(detail, {
        "bg.logistics.shippingservices.get": SERVICES,
        "bg.logistics.shipment.create": {"packageSnList": ["PK-NEW"], "warningMessage": []},
    }))
    package_sn = adapter.create_shipment(detail["parentOrderMap"]["parentOrderSn"], "7", "WH-1", ship_later=True)
    assert package_sn == "PK-NEW"
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.logistics.shipment.create" and body["shipLater"] is True and body["sendType"] == 0
    [req] = body["sendRequestList"]
    assert req["channelId"] == 7 and req["shipCompanyId"] == 3 and req["warehouseId"] == "WH-1"
    assert req["orderSendInfoList"][0]["parentOrderSn"] == detail["parentOrderMap"]["parentOrderSn"]


def test_shipment_result_status_mapping(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", ok({"packageInfoResultList": [
        {"packageSn": "PK-1", "shippingLabelStatus": 2, "failReasonText": "no service", "trackingNumber": ""}]}))
    r = adapter.get_shipment_result("PK-1")
    assert r.status == "failed" and r.error == "no service" and r.package_sn == "PK-1"
    assert fake.last_call().kwargs["json"]["packageSnList"] == ["PK-1"]
    fake.add("POST", "openapi/router", ok({"packageInfoResultList": [
        {"packageSn": "PK-1", "shippingLabelStatus": 1, "trackingNumber": "TRK1", "shipLogisticsType": "LOCAL",
         "interlineShipCompanyList": [{"shippingCompanyName": "Curier Rapid"}]}]}))
    fake.responses.reverse()
    r = adapter.get_shipment_result("PK-1")
    assert r.status == "success" and r.tracking_number == "TRK1" and r.carrier == "Curier Rapid"
    fake.add("POST", "openapi/router", ok({"packageInfoResultList": []}))
    fake.responses.reverse()
    assert adapter.get_shipment_result("PK-1").status == "pending"


def test_confirm_package_shipped(fake):
    adapter = _adapter(fake)
    fake.add("POST", "openapi/router", ok({"warningMessage": []}))
    adapter.confirm_package_shipped("PK-1")
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.logistics.shipped.package.confirm" and body["packageSendInfoList"] == [{"packageSn": "PK-1"}]


def test_get_order_awbs_from_packages(fake):
    adapter = _adapter(fake)
    detail = load("order_detail.json")
    fake.add("POST", "openapi/router", _router(detail, {"bg.logistics.shipment.result.get": {"packageInfoResultList": [
        {"packageSn": detail["orderList"][0]["packageSnInfo"][0]["packageSn"], "shippingLabelStatus": 1, "trackingNumber": "TRK9"}]}}))
    [awb] = adapter.get_order_awbs(detail["parentOrderMap"]["parentOrderSn"])
    assert awb.tracking_number == "TRK9" and awb.extra["package_sn"].startswith("PK-")


def test_get_awb_pdf_downloads_signed_url(fake):
    adapter = _adapter(fake)

    class Resp:
        content = b"%PDF-1.4"

    def route(method, path, kwargs):
        if method == "GET":
            return Resp()
        assert kwargs["json"]["documentType"] == LABEL_DOCUMENT_TYPE and kwargs["json"]["packageSnList"] == ["PK-1"]
        return ok({"shippingLabelUrlList": [{"packageSn": "PK-1", "documentType": LABEL_DOCUMENT_TYPE,
                                            "url": "https://files.example.test/label.pdf"}]})

    fake.add(None, "", route)
    assert adapter.get_awb_pdf("PK-1") == b"%PDF-1.4"
    assert fake.last_call().path == "https://files.example.test/label.pdf"
    assert set(fake.last_call().kwargs["headers"]) >= {"toa-app-key", "toa-sign", "toa-random", "toa-timestamp", "toa-access-token"}


def test_shipping_service_dto_is_plain():
    assert ShippingService(service_id="7", name="x").carrier_id == ""
