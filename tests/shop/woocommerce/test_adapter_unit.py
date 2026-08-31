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
