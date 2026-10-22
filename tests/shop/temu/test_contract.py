"""The generic ShopPort contract, run offline against the Temu fixtures."""

import pytest

from bapp_connectors.providers.shop.temu.adapter import REQUIRED_SCOPES, TemuShopAdapter
from tests.fake_http import FakeHttpClient
from tests.shop.contract import ShopContractTests
from tests.shop.temu.conftest import CREDS, err, ok
from tests.shop.temu.test_orders_unit import load


class TestTemuShopContract(ShopContractTests):
    @pytest.fixture
    def adapter(self):
        fake = FakeHttpClient()
        responses = {
            "bg.open.accesstoken.info.get": ok({"mallId": 42, "apiScopeList": list(REQUIRED_SCOPES), "expiredTime": 1824222274}),
            "temu.local.mall.settlestatus.get": ok({"mallId": 42, "mallName": "Shop", "settleStatus": 99}),
            "bg.order.list.v2.get": ok({**load("order_list.json"), "totalItemNum": 3}),
            "bg.order.shippinginfo.v2.get": ok(load("shipping_info.json")),
            "temu.order.amount.v2.query": err(3000032, "no scope"),
            "temu.pay.tax.invoice.detail.query": ok({"invoiceDetailInfoList": None}),
            "bg.local.goods.list.query": ok(load("goods_list.json")),
        }
        fake.add("POST", "openapi/router", lambda m, p, kw: responses[kw["json"]["type"]])
        return TemuShopAdapter(CREDS, http_client=fake, config={})
