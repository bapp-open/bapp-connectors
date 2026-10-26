from decimal import Decimal

import pytest

from bapp_connectors.core.dto import Product, ProductAttribute, ProductPhoto, ProductUpdate, ProductVariant
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.shop.temu.adapter import TemuShopAdapter
from bapp_connectors.providers.shop.temu.mappers import goods_v3_payload, product_from_goods
from tests.shop.temu.conftest import CREDS, ok
from tests.shop.temu.test_orders_unit import load

CFG = {"default_weight_g": 100, "default_length_cm": 10, "default_width_cm": 20, "default_height_cm": 30,
       "currency": "RON", "shipment_limit_day": None}


def _product(**kw):
    base = {"product_id": "", "sku": "SKU-1", "barcode": "5941234567890", "name": "Lampa", "description": "<p>desc</p>",
            "price": Decimal("49.9"), "currency": "RON", "stock": 7, "categories": ["Casa", "Lampi"],
            "photos": [ProductPhoto(url="https://cdn.example.test/a.jpg", position=0)]}
    base.update(kw)
    return Product(**base)


def test_v3_payload_required_fields():
    p = goods_v3_payload(_product(), CFG)
    assert p["goodsBasic"]["externalGoodsId"] == "SKU-1" and p["goodsBasic"]["goodsName"] == "Lampa"
    assert p["goodsBasic"]["extCatName"] == "Casa / Lampi" and p["goodsBasic"]["goodsDesc"] == "<p>desc</p>"
    assert p["goodsBasic"]["goodsCarouselImage"] == ["https://cdn.example.test/a.jpg"] and p["goodsBasic"]["productType"] == 1
    assert "shipmentLimitDay" not in p["goodsBasic"] and "attributes" not in p
    sku = p["skuList"][0]
    assert sku["externalSkuId"] == "SKU-1" and sku["images"] == ["https://cdn.example.test/a.jpg"]
    assert sku["price"]["basePrice"] == {"amount": "49.90", "currency": "RON"} and sku["quantity"] == 7
    assert sku["packageInfo"] == {"weight": "100", "length": "10", "width": "20", "height": "30"}
    assert sku["variations"] == [{"name": "Color", "value": "as shown"}]
    assert sku["barCode"] == {"barCodeType": "EAN", "barCodeId": ["5941234567890"]}


def test_v3_payload_uses_package_extra_attributes_and_limit_day():
    product = _product(extra={"package": {"weight_g": 250, "length_cm": 30, "width_cm": 10, "height_cm": 5}, "brand": "Acme"},
                       attributes=[ProductAttribute(attribute_id="1", attribute_name="Material", values=["lemn"]),
                                   ProductAttribute(attribute_id="2", attribute_name="Culoare", values=["roșu"], used_for_variants=True)])
    p = goods_v3_payload(product, {**CFG, "shipment_limit_day": 3})
    assert p["skuList"][0]["packageInfo"] == {"weight": "250", "length": "30", "width": "10", "height": "5"}
    assert p["goodsBasic"]["shipmentLimitDay"] == 3
    assert p["attributes"] == [{"name": "Material", "value": ["lemn"]}, {"name": "Brand", "value": ["Acme"]}]


def test_v3_payload_variants_become_sku_list():
    product = _product(variants=[
        ProductVariant(variant_id="", sku="SKU-1-R", barcode="5941234567891", price=Decimal("50"), stock=2,
                       attributes={"Culoare": "roșu"}, image_url="https://cdn.example.test/r.jpg"),
        ProductVariant(variant_id="", sku="SKU-1-A", price=Decimal("51"), stock=0, attributes={"Culoare": "albastru"}),
    ])
    p = goods_v3_payload(product, CFG)
    assert [s["externalSkuId"] for s in p["skuList"]] == ["SKU-1-R", "SKU-1-A"]
    assert p["skuList"][0]["images"] == ["https://cdn.example.test/r.jpg"] and p["skuList"][1]["images"] == ["https://cdn.example.test/a.jpg"]
    assert p["skuList"][0]["variations"] == [{"name": "Culoare", "value": "roșu"}] and p["skuList"][1]["quantity"] == 0
    assert p["skuList"][0]["barCode"]["barCodeId"] == ["5941234567891"] and "barCode" not in p["skuList"][1]


def test_v3_payload_requires_an_image_and_a_sku():
    with pytest.raises(ValidationError):
        goods_v3_payload(_product(photos=[]), CFG)
    with pytest.raises(ValidationError):
        goods_v3_payload(_product(sku=None), CFG)


def test_create_product_returns_goods_id(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", ok({"goodsId": 608573962731830, "externalGoodsId": "SKU-1"}))
    created = adapter.create_product(_product())
    assert created.product_id == "608573962731830" and created.sku == "SKU-1" and created.extra["status"] == "draft"
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "temu.local.goods.v3.add" and body["goodsBasic"]["externalGoodsId"] == "SKU-1"


def test_delete_product(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", ok({}))
    adapter.delete_product("500")
    assert fake.last_call().kwargs["json"] | {"type": "temu.local.goods.delete", "goodsId": 500} == fake.last_call().kwargs["json"]


def _stock_router(extra=None):
    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        if t == "temu.local.goods.sku.stock.query":
            return ok({"stockList": [{"goodsId": kwargs["json"]["goodsId"], "skuStockInfoList": [{"skuId": 11, "outSkuSn": "SKU-1", "selfOrdinaryStock": {"stockType": 0, "stock": 5}}]}]})
        if extra and t in extra:
            return extra[t]
        return ok({})
    return route


def test_update_stock_resolves_sku_ids_then_edits(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", _stock_router())
    adapter.update_product_stock("500", 3)
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.local.goods.stock.edit" and body["goodsId"] == 500
    assert body["skuStockTargetList"] == [{"skuId": 11, "stockTarget": 3}] and len(body["requestUniqueKey"]) == 32
    assert "stockType" not in body
    assert fake.calls[0].kwargs["json"]["goodsId"] == 500


def test_update_price_resolves_sku_ids(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", _stock_router())
    adapter.update_product_price("500", Decimal("12.5"), "RON")
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.local.goods.priceorder.change.sku.price" and body["goodsId"] == 500
    [dto] = body["changeSkuPriceDTOList"]
    assert dto["skuChangePriceBaseDTOList"] == [{"skuId": 11, "newSupplierPrice": {"amount": "12.50", "currency": "RON"}}]
    assert dto["reason"]


def test_update_product_only_sends_given_fields(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", _stock_router())
    adapter.update_product(ProductUpdate(product_id="500", name="Lampa 2", stock=4))
    types = [c.kwargs["json"]["type"] for c in fake.calls]
    assert types == ["bg.local.goods.partial.update", "temu.local.goods.sku.stock.query", "bg.local.goods.stock.edit"]
    partial = fake.calls[0].kwargs["json"]
    assert partial["goodsId"] == 500 and partial["goodsBasic"] == {"goodsName": "Lampa 2"} and "goodsDesc" not in partial


def test_get_products_null_result_is_empty_page(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", ok(None))
    page = adapter.get_products()
    assert page.items == [] and page.has_more is False and page.cursor is None


def test_get_products_maps_goods_list(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", ok(load("goods_list.json")))
    page = adapter.get_products(cursor="1")
    body = fake.last_call().kwargs["json"]
    assert body["pageNo"] == 1 and body["goodsSearchType"] == 1 and body["statusFilterType"] == 0
    product = page.items[0]
    assert product.product_id.isdigit() and product.name.startswith("Produs test")
    assert product.variants and product.variants[0].variant_id.isdigit() and product.provider_meta.provider == "temu"
    assert "goodsStatus" in product.extra or "goodsShowSubStatus" in product.extra


def test_product_from_goods_stock_is_sum_of_skus():
    item = {"goodsId": 1, "goodsName": "X", "outGoodsSn": "X-1", "currency": "RON", "price": "9.90",
            "skuInfoList": [{"skuId": 10, "skuSn": "X-1-A", "stock": 2, "specList": [{"parentSpecName": "Color", "specName": "red"}]},
                            {"skuId": 11, "skuSn": "X-1-B", "stock": 3, "specList": []}]}
    p = product_from_goods(item)
    assert p.stock == 5 and p.sku == "X-1" and p.price == Decimal("9.90") and p.currency == "RON"
    assert p.variants[0].attributes == {"Color": "red"} and p.variants[1].sku == "X-1-B"


def test_bulk_update_counts(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)

    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        if t == "temu.local.goods.sku.stock.query":
            if kwargs["json"]["goodsId"] == 999:
                return {"success": False, "errorCode": 7000000, "errorMsg": "BUSINESS_SERVICE_ERROR", "requestId": "r"}
            return ok({"stockList": [{"goodsId": 500, "skuStockInfoList": [{"skuId": 11, "outSkuSn": "SKU-1"}]}]})
        return ok({})

    fake.add("POST", "openapi/router", route)
    res = adapter.bulk_update_products([ProductUpdate(product_id="500", sku="SKU-1", stock=1),
                                        ProductUpdate(product_id="999", sku="SKU-9", stock=2),
                                        ProductUpdate(product_id="500", sku="SKU-1", price=Decimal("3"))])
    assert (res.total, res.succeeded, res.failed) == (3, 2, 1)
    assert res.errors[0]["product_id"] == "999" and "BUSINESS_SERVICE_ERROR" in res.errors[0]["error"]


def test_product_from_goods_publication_state():
    base = {"goodsId": 1, "goodsName": "X", "outGoodsSn": "X-1", "skuInfoList": []}
    assert product_from_goods({**base, "goodsShowSubStatus": 2001}).active is True
    assert product_from_goods({**base, "goodsShowSubStatus": 2001}).extra["status"] == "on_sale"
    assert product_from_goods({**base, "goodsShowSubStatus": 3002}).active is False
    assert product_from_goods({**base, "goodsShowSubStatus": 3002}).extra["status"] == "off_sale"
    assert product_from_goods({**base, "goodsShowSubStatus": 4002}).active is False
    assert product_from_goods({**base, "goodsShowSubStatus": 4002}).extra["status"] == "incomplete"
    assert product_from_goods(base).active is True and product_from_goods(base).extra["status"] == "unknown"


def _sku_query_router(calls):
    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        calls.append(t)
        if t == "temu.local.goods.sku.stock.query":
            # by SKU (host stock push: product_id is the SKU) or by goods id (sku given only as a hint)
            assert kwargs["json"].get("outSkuSnList") == ["SKU-2"] or kwargs["json"].get("goodsId") == 500
            return ok({"stockList": [{"goodsId": 500, "skuStockInfoList": [{"skuId": 11, "outSkuSn": "SKU-1"}, {"skuId": 12, "outSkuSn": "SKU-2"}]}]})
        return ok({})
    return route


def test_bulk_update_by_sku_resolves_goods_and_touches_only_that_sku(fake):
    # the host's stock push sends ProductUpdate(product_id=<sku>, sku=<sku>, stock=qty)
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    calls = []
    fake.add("POST", "openapi/router", _sku_query_router(calls))
    res = adapter.bulk_update_products([ProductUpdate(product_id="SKU-2", sku="SKU-2", stock=4, price=Decimal("7"))])
    assert (res.total, res.succeeded, res.failed) == (1, 1, 0)
    assert calls == ["temu.local.goods.sku.stock.query", "bg.local.goods.stock.edit", "bg.local.goods.priceorder.change.sku.price"]
    stock_body = fake.calls[1].kwargs["json"]
    assert stock_body["goodsId"] == 500 and stock_body["skuStockTargetList"] == [{"skuId": 12, "stockTarget": 4}]
    price_body = fake.calls[2].kwargs["json"]
    assert price_body["goodsId"] == 500 and price_body["changeSkuPriceDTOList"][0]["skuChangePriceBaseDTOList"][0]["skuId"] == 12


def test_update_stock_with_sku_hint_touches_only_that_sku(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    calls = []
    fake.add("POST", "openapi/router", _sku_query_router(calls))
    adapter.update_product(ProductUpdate(product_id="500", sku="SKU-2", stock=1))
    assert fake.last_call().kwargs["json"]["skuStockTargetList"] == [{"skuId": 12, "stockTarget": 1}]


def test_unknown_sku_is_a_failed_row(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config=CFG)
    fake.add("POST", "openapi/router", ok({"stockList": []}))
    res = adapter.bulk_update_products([ProductUpdate(product_id="NOPE", sku="NOPE", stock=1)])
    assert res.failed == 1 and "NOPE" in res.errors[0]["error"]
