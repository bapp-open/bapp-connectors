"""`product/inventory/json`: the shape Gomag actually applies.

A bare list with `quantity` gets a 200 and changes nothing; Gomag support gave the
working form: `data={"products": [{"sku": ..., "stock": ...}]}`.
"""
import json

from bapp_connectors.core.dto.product import ProductUpdate
from bapp_connectors.providers.shop.gomag.adapter import GomagShopAdapter
from bapp_connectors.providers.shop.gomag.client import GomagApiClient


class FakeHttp:
    def __init__(self):
        self.calls = []

    def call(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {}


def _sent(http):
    (method, path, kwargs), = http.calls
    return method, path, json.loads(kwargs["data"]["data"]), kwargs


def test_inventory_is_sent_under_products_with_stock():
    http = FakeHttp()
    GomagApiClient(http_client=http).update_product_inventory([{"sku": "7A58-43", "stock": 1135}])
    method, path, data, _ = _sent(http)
    assert (method, path) == ("POST", "product/inventory/json")
    assert data == {"products": [{"sku": "7A58-43", "stock": 1135}]}


def test_the_answer_is_kept_in_the_execution_log():
    http = FakeHttp()
    GomagApiClient(http_client=http).update_product_inventory([{"sku": "A", "stock": 1}])
    assert _sent(http)[3]["log_body"] is True


def test_adapter_stock_update_and_bulk_use_stock():
    http = FakeHttp()
    adapter = GomagShopAdapter(credentials={"token": "t", "shop_site": "https://s.ro"})
    adapter.client = GomagApiClient(http_client=http)
    adapter.update_product_stock("7A58-43", 1135)
    adapter.bulk_update_products([ProductUpdate(product_id="B-1", sku="B-1", stock=4)])
    payloads = [json.loads(kwargs["data"]["data"]) for _, _, kwargs in http.calls]
    assert payloads == [{"products": [{"sku": "7A58-43", "stock": 1135}]},
                        {"products": [{"sku": "B-1", "stock": 4}]}]
