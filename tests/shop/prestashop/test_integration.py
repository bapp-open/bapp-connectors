"""
PrestaShop integration tests — runs against PrestaShop 8 in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d presta-db prestashop
    python scripts/setup_prestashop.py
    uv run --extra dev pytest tests/shop/prestashop/ -v -m integration
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import (
    Order,
    PaginatedResult,
    Product,
    ProductCategory,
)
from tests.shop.conftest import (
    PS_API_KEY,
    PS_HOST,
    PS_PORT,
    skip_unless_prestashop,
)

pytestmark = [pytest.mark.integration, skip_unless_prestashop]


@pytest.fixture
def adapter():
    from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter

    return PrestaShopShopAdapter(
        credentials={
            "domain": f"http://{PS_HOST}:{PS_PORT}",
            "token": PS_API_KEY,
        },
        config={
            "prices_include_vat": False,
            "use_query_auth": True,
        },
    )


# ── Contract Tests ──


class TestPrestaShopContract:
    """Run the shop contract suite against PrestaShop."""

    from tests.shop.contract import ShopContractTests

    for _name, _method in vars(ShopContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Products ──


class TestPrestaShopProducts:

    def test_get_products_returns_list(self, adapter):
        result = adapter.get_products()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    def test_create_and_get_product(self, adapter):
        created = adapter.create_product(Product(
            product_id="ignored",
            name=f"PS Test Product {uuid.uuid4().hex[:6]}",
            sku=f"PS-{uuid.uuid4().hex[:6]}",
            price=Decimal("25.00"),
            active=True,
        ))

        try:
            assert created.product_id

            # Verify it shows in product list
            products = adapter.get_products()
            ids = [p.product_id for p in products.items]
            assert created.product_id in ids
        finally:
            adapter.delete_product(created.product_id)

    def test_update_product_price(self, adapter):
        created = adapter.create_product(Product(
            product_id="ignored",
            name=f"PS Price Test {uuid.uuid4().hex[:6]}",
            price=Decimal("10.00"),
        ))

        try:
            adapter.update_product_price(created.product_id, Decimal("19.99"), "RON")
            updated = adapter.client.get_product(int(created.product_id))
            assert Decimal(str(updated.get("price", 0))) == Decimal("19.99")
        finally:
            adapter.delete_product(created.product_id)

    def test_delete_product(self, adapter):
        created = adapter.create_product(Product(
            product_id="ignored",
            name=f"PS Delete Test {uuid.uuid4().hex[:6]}",
            price=Decimal("5.00"),
        ))

        adapter.delete_product(created.product_id)

        products = adapter.get_products()
        assert created.product_id not in [p.product_id for p in products.items]

    def test_full_update_product(self, adapter):
        from bapp_connectors.core.dto import ProductUpdate

        created = adapter.create_product(Product(
            product_id="ignored",
            name=f"PS Full Update {uuid.uuid4().hex[:6]}",
            price=Decimal("15.00"),
        ))

        try:
            adapter.update_product(ProductUpdate(
                product_id=created.product_id,
                name=f"PS Updated Name {uuid.uuid4().hex[:6]}",
                price=Decimal("29.99"),
            ))

            updated = adapter.client.get_product(int(created.product_id))
            assert Decimal(str(updated.get("price", 0))) == Decimal("29.99")
        finally:
            adapter.delete_product(created.product_id)


# ── Categories ──


class TestPrestaShopCategories:

    def test_get_categories(self, adapter):
        categories = adapter.get_categories()
        assert isinstance(categories, list)
        assert len(categories) > 0  # PrestaShop has default categories
        for cat in categories:
            assert isinstance(cat, ProductCategory)
            assert cat.category_id
            assert cat.name

    def test_create_category(self, adapter):
        cat_name = f"PS Test Cat {uuid.uuid4().hex[:6]}"
        created = adapter.create_category(cat_name)

        try:
            assert created.category_id
            assert cat_name in created.name

            categories = adapter.get_categories()
            cat_ids = [c.category_id for c in categories]
            assert created.category_id in cat_ids
        finally:
            adapter.client._call("DELETE", f"categories/{created.category_id}")

    def test_create_category_with_parent(self, adapter):
        parent_name = f"PS Parent {uuid.uuid4().hex[:6]}"
        child_name = f"PS Child {uuid.uuid4().hex[:6]}"

        parent = adapter.create_category(parent_name)
        try:
            child = adapter.create_category(child_name, parent_id=parent.category_id)
            try:
                assert child.parent_id == parent.category_id
            finally:
                adapter.client._call("DELETE", f"categories/{child.category_id}")
        finally:
            adapter.client._call("DELETE", f"categories/{parent.category_id}")


# ── Sync Engine ──


class TestPrestaShopSyncEngine:

    def test_pull_products(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        received = []
        result = engine.pull_products(adapter, on_product=received.append)
        assert result.failed == 0

    def test_push_creates_product(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        product = Product(
            product_id="local_ps_1",
            name=f"PS Sync Product {uuid.uuid4().hex[:6]}",
            price=Decimal("12.00"),
            active=True,
        )

        result = engine.push_products(adapter, [product])
        assert result.created == 1
        assert result.failed == 0

        # Cleanup
        products = adapter.get_products()
        for p in products.items:
            if "PS Sync Product" in p.name:
                adapter.delete_product(p.product_id)

    def test_pull_categories(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        categories = engine.pull_categories(adapter)
        assert len(categories) > 0

    def test_push_categories(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        cat_name = f"PS Engine Cat {uuid.uuid4().hex[:6]}"
        categories = [ProductCategory(category_id="local_ps_cat", name=cat_name)]

        mappings = engine.push_categories(adapter, categories)
        assert len(mappings) == 1
        assert mappings[0].local_id == "local_ps_cat"

        # Cleanup
        adapter.client._call("DELETE", f"categories/{mappings[0].remote_id}")


# ── Orders ──


class TestPrestaShopOrders:

    def test_get_orders(self, adapter):
        result = adapter.get_orders()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    def test_orders_have_raw_status(self, adapter):
        result = adapter.get_orders()
        for order in result.items:
            assert isinstance(order, Order)
            # raw_status should be the PrestaShop state ID
            assert order.raw_status is not None


# ── Errors ──


class TestPrestaShopErrors:

    def test_unreachable_host(self):
        from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter

        adapter = PrestaShopShopAdapter(credentials={
            "domain": "http://127.0.0.1:19999",
            "token": "invalid",
        })
        result = adapter.test_connection()
        assert result.success is False

    def test_missing_credentials(self):
        from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter

        adapter = PrestaShopShopAdapter(credentials={})
        assert adapter.validate_credentials() is False
