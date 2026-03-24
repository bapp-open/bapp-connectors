"""
Magento 2 integration tests — runs against Magento 2 in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d magento-db magento
    python scripts/setup_magento.py  # outputs the access_token
    MG_ACCESS_TOKEN=<token> uv run --extra dev pytest tests/shop/magento/ -v -m integration
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
    ProductUpdate,
)
from tests.shop.conftest import (
    MG_ACCESS_TOKEN,
    MG_HOST,
    MG_PORT,
    skip_unless_magento,
)

pytestmark = [pytest.mark.integration, skip_unless_magento]


@pytest.fixture
def adapter():
    from bapp_connectors.providers.shop.magento.adapter import MagentoShopAdapter

    token = MG_ACCESS_TOKEN
    if not token:
        pytest.skip("MG_ACCESS_TOKEN not set. Run: python scripts/setup_magento.py")

    return MagentoShopAdapter(
        credentials={
            "domain": f"http://{MG_HOST}:{MG_PORT}",
            "access_token": token,
        },
        config={
            "store_code": "default",
            "prices_include_vat": False,
        },
    )


@pytest.fixture
def test_product(adapter):
    """Create a test product and clean up after."""
    sku = f"INT-TEST-{uuid.uuid4().hex[:6]}"
    created = adapter.create_product(Product(
        product_id="ignored",
        sku=sku,
        name=f"Integration Test Product {sku}",
        price=Decimal("19.99"),
        active=True,
    ))
    yield created
    try:
        adapter.delete_product(created.sku or created.product_id)
    except Exception:
        pass


# ── Contract Tests ──


class TestMagentoContract:
    from tests.shop.contract import ShopContractTests

    for _name, _method in vars(ShopContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Products ──


class TestMagentoProducts:

    def test_create_and_get_product(self, adapter, test_product):
        assert test_product.product_id
        assert test_product.sku

        products = adapter.get_products()
        skus = [p.sku for p in products.items]
        assert test_product.sku in skus

    def test_update_product_price(self, adapter, test_product):
        adapter.update_product_price(test_product.sku, Decimal("29.99"), "RON")
        updated = adapter.client.get_product(test_product.sku)
        assert Decimal(str(updated.get("price", 0))) == Decimal("29.99")

    def test_full_update_product(self, adapter, test_product):
        adapter.update_product(ProductUpdate(
            product_id=test_product.product_id,
            sku=test_product.sku,
            name=f"Updated {uuid.uuid4().hex[:6]}",
            price=Decimal("39.99"),
        ))
        updated = adapter.client.get_product(test_product.sku)
        assert Decimal(str(updated.get("price", 0))) == Decimal("39.99")

    def test_delete_product(self, adapter):
        sku = f"DEL-TEST-{uuid.uuid4().hex[:6]}"
        created = adapter.create_product(Product(
            product_id="ignored",
            sku=sku,
            name=f"Delete Test {sku}",
            price=Decimal("5.00"),
        ))
        adapter.delete_product(created.sku)

        products = adapter.get_products()
        assert sku not in [p.sku for p in products.items]


# ── Categories ──


class TestMagentoCategories:

    def test_get_categories(self, adapter):
        categories = adapter.get_categories()
        assert isinstance(categories, list)
        assert len(categories) > 0
        for cat in categories:
            assert isinstance(cat, ProductCategory)

    def test_create_category(self, adapter):
        cat_name = f"MG Test Cat {uuid.uuid4().hex[:6]}"
        created = adapter.create_category(cat_name)
        try:
            assert created.category_id
            assert cat_name in created.name
        finally:
            try:
                adapter.client.http.call("DELETE", f"categories/{created.category_id}")
            except Exception:
                pass


# ── Orders ──


class TestMagentoOrders:

    def test_get_orders(self, adapter):
        result = adapter.get_orders()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    def test_orders_have_raw_status(self, adapter):
        result = adapter.get_orders()
        for order in result.items:
            assert isinstance(order, Order)
            assert order.raw_status is not None


# ── Sync Engine ──


class TestMagentoSyncEngine:

    def test_pull_products(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        received = []
        result = engine.pull_products(adapter, on_product=received.append)
        assert result.failed == 0

    def test_push_creates_product(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine

        sku = f"SYNC-{uuid.uuid4().hex[:6]}"
        engine = ProductSyncEngine()
        product = Product(
            product_id="local_mg_1",
            sku=sku,
            name=f"MG Sync Product {sku}",
            price=Decimal("12.00"),
            active=True,
        )

        result = engine.push_products(adapter, [product])
        assert result.created == 1

        try:
            adapter.delete_product(sku)
        except Exception:
            pass

    def test_pull_categories(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        categories = engine.pull_categories(adapter)
        assert len(categories) > 0


# ── Errors ──


class TestMagentoErrors:

    def test_unreachable_host(self):
        from bapp_connectors.providers.shop.magento.adapter import MagentoShopAdapter

        adapter = MagentoShopAdapter(credentials={
            "domain": "http://127.0.0.1:19999",
            "access_token": "invalid",
        })
        result = adapter.test_connection()
        assert result.success is False

    def test_missing_credentials(self):
        from bapp_connectors.providers.shop.magento.adapter import MagentoShopAdapter

        adapter = MagentoShopAdapter(credentials={})
        assert adapter.validate_credentials() is False
