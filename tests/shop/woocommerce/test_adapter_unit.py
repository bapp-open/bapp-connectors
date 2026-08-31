"""WooCommerce adapter tests against FakeHttpClient — no Docker."""
from __future__ import annotations

import pytest

from bapp_connectors.core.dto import ProductCategory
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from tests.fake_http import FakeHttpClient


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    # No domain => the adapter keeps the injected http client instead of building a real one.
    return WooCommerceShopAdapter(credentials={"consumer_key": "k", "consumer_secret": "s"}, http_client=fake)


def test_update_category_puts_name_and_parent(adapter, fake):
    fake.add("PUT", "products/categories/7", {"id": 7, "name": "Scule electrice", "parent": 3})
    result = adapter.update_category(ProductCategory(category_id="7", name="Scule electrice", parent_id="3"))
    assert result.category_id == "7"
    assert result.parent_id == "3"
    call = fake.last_call()
    assert call.method == "PUT" and call.path == "products/categories/7"
    assert call.kwargs["json"] == {"name": "Scule electrice", "parent": 3}


def test_update_category_root_sends_parent_zero(adapter, fake):
    fake.add("PUT", "products/categories/7", {"id": 7, "name": "Scule", "parent": 0})
    result = adapter.update_category(ProductCategory(category_id="7", name="Scule"))
    assert fake.last_call().kwargs["json"] == {"name": "Scule", "parent": 0}
    assert result.parent_id is None


def test_find_product_by_sku_returns_product(adapter, fake):
    fake.add("GET", "products", [{"id": 55, "sku": "AB-1", "name": "Ciocan", "price": "10", "status": "publish"}])
    product = adapter.find_product_by_sku("AB-1")
    assert product is not None and product.product_id == "55"
    assert fake.last_call().kwargs["params"]["sku"] == "AB-1"
    assert fake.last_call().kwargs["params"]["per_page"] == 1


def test_find_product_by_sku_empty_list_is_none(adapter, fake):
    fake.add("GET", "products", [])
    assert adapter.find_product_by_sku("NOPE") is None


def test_find_product_by_sku_blank_sku_short_circuits(adapter, fake):
    assert adapter.find_product_by_sku("") is None
    assert fake.calls == []


def test_woocommerce_declares_lookup_capability():
    from bapp_connectors.core.capabilities import ProductLookupCapability
    from bapp_connectors.providers.shop.woocommerce.manifest import manifest

    assert ProductLookupCapability in manifest.capabilities
