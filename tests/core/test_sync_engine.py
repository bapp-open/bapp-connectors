"""Tests for the ProductSyncEngine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import (
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
)
from bapp_connectors.core.dto import (
    ConnectionTestResult,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductCategory,
    ProductPhoto,
    ProductUpdate,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.sync import ProductSyncEngine, SyncResult


# ── Mock adapters ──


class _MockShopAdapter(ShopPort):
    """Minimal ShopPort — read-only, no creation."""

    manifest = None  # type: ignore

    def __init__(self, products: list[Product] | None = None):
        self._products = products or []
        self.stock_updates: list[tuple] = []
        self.price_updates: list[tuple] = []

    def validate_credentials(self) -> bool:
        return True

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(success=True)

    def get_orders(self, since=None, cursor=None):
        return PaginatedResult(items=[])

    def get_order(self, order_id):
        return {}

    def get_products(self, cursor=None):
        return PaginatedResult(items=self._products, has_more=False)

    def update_product_stock(self, product_id, quantity):
        self.stock_updates.append((product_id, quantity))

    def update_product_price(self, product_id, price, currency):
        self.price_updates.append((product_id, price, currency))

    def update_order_status(self, order_id, status):
        raise NotImplementedError


class _MockFullAdapter(
    _MockShopAdapter, ProductCreationCapability, ProductFullUpdateCapability, CategoryManagementCapability
):
    """Full adapter with creation, update, and category capabilities."""

    def __init__(self, products=None, categories=None):
        super().__init__(products)
        self._categories = categories or []
        self.created_products: list[Product] = []
        self.deleted_products: list[str] = []
        self.full_updates: list[ProductUpdate] = []
        self.created_categories: list[tuple] = []

    def create_product(self, product: Product) -> Product:
        self.created_products.append(product)
        return product.model_copy(update={"product_id": f"remote_{product.product_id}"})

    def delete_product(self, product_id: str) -> None:
        self.deleted_products.append(product_id)

    def update_product(self, update: ProductUpdate) -> None:
        self.full_updates.append(update)

    def get_categories(self) -> list[ProductCategory]:
        return self._categories

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        self.created_categories.append((name, parent_id))
        return ProductCategory(category_id=f"remote_cat_{len(self.created_categories)}", name=name, parent_id=parent_id)


# ── Tests ──


class TestPullProducts:

    def test_pull_calls_callback_for_each_product(self):
        products = [
            Product(product_id="1", name="A"),
            Product(product_id="2", name="B"),
        ]
        adapter = _MockShopAdapter(products=products)
        engine = ProductSyncEngine()

        received = []
        result = engine.pull_products(adapter, on_product=received.append)

        assert len(received) == 2
        assert result.updated == 2
        assert result.failed == 0

    def test_pull_records_callback_errors(self):
        products = [Product(product_id="1", name="A")]
        adapter = _MockShopAdapter(products=products)
        engine = ProductSyncEngine()

        def failing_callback(p):
            raise ValueError("DB error")

        result = engine.pull_products(adapter, on_product=failing_callback)
        assert result.failed == 1
        assert result.errors[0].product_id == "1"
        assert "DB error" in result.errors[0].error

    def test_pull_empty_store(self):
        adapter = _MockShopAdapter(products=[])
        engine = ProductSyncEngine()
        result = engine.pull_products(adapter, on_product=lambda p: None)
        assert result.updated == 0


class TestPushProducts:

    def test_push_creates_new_products(self):
        adapter = _MockFullAdapter()
        engine = ProductSyncEngine()
        products = [Product(product_id="local_1", name="New Product", price=Decimal("10.00"))]

        result = engine.push_products(adapter, products)

        assert result.created == 1
        assert len(adapter.created_products) == 1
        assert adapter.created_products[0].name == "New Product"

    def test_push_updates_existing_products(self):
        adapter = _MockFullAdapter()
        engine = ProductSyncEngine()
        products = [Product(product_id="local_1", name="Updated", price=Decimal("20.00"), stock=5)]

        def match(p):
            return "remote_1"

        result = engine.push_products(adapter, products, match_fn=match)

        assert result.updated == 1
        assert len(adapter.full_updates) == 1
        assert adapter.full_updates[0].product_id == "remote_1"
        assert adapter.full_updates[0].name == "Updated"

    def test_push_skips_when_no_creation_capability(self):
        adapter = _MockShopAdapter()  # no ProductCreationCapability
        engine = ProductSyncEngine()
        products = [Product(product_id="1", name="Cannot Create")]

        result = engine.push_products(adapter, products)

        assert result.skipped == 1
        assert result.created == 0

    def test_push_falls_back_to_stock_price_without_full_update(self):
        adapter = _MockShopAdapter()
        engine = ProductSyncEngine()
        products = [Product(product_id="1", name="X", price=Decimal("10"), stock=5, currency="RON")]

        def match(p):
            return "remote_1"

        result = engine.push_products(adapter, products, match_fn=match)

        assert result.updated == 1
        assert adapter.stock_updates == [("remote_1", 5)]
        assert adapter.price_updates == [("remote_1", Decimal("10"), "RON")]

    def test_push_records_errors(self):
        class _FailingAdapter(_MockFullAdapter):
            def create_product(self, product):
                raise RuntimeError("API down")

        adapter = _FailingAdapter()
        engine = ProductSyncEngine()
        products = [Product(product_id="1", name="Will Fail")]

        result = engine.push_products(adapter, products)

        assert result.failed == 1
        assert "API down" in result.errors[0].error

    def test_push_with_photos(self):
        adapter = _MockFullAdapter()
        engine = ProductSyncEngine()
        products = [Product(
            product_id="1",
            name="With Photos",
            photos=[ProductPhoto(url="https://example.com/img.jpg", alt_text="Test")],
        )]

        result = engine.push_products(adapter, products)
        assert result.created == 1


class TestPullCategories:

    def test_pull_returns_categories(self):
        cats = [
            ProductCategory(category_id="1", name="Electronics"),
            ProductCategory(category_id="2", name="Phones", parent_id="1"),
        ]
        adapter = _MockFullAdapter(categories=cats)
        engine = ProductSyncEngine()

        result = engine.pull_categories(adapter)
        assert len(result) == 2
        assert result[1].parent_id == "1"

    def test_pull_raises_without_capability(self):
        adapter = _MockShopAdapter()
        engine = ProductSyncEngine()

        with pytest.raises(TypeError, match="CategoryManagementCapability"):
            engine.pull_categories(adapter)


class TestPushCategories:

    def test_push_creates_categories(self):
        adapter = _MockFullAdapter()
        engine = ProductSyncEngine()
        cats = [
            ProductCategory(category_id="local_1", name="Electronics"),
            ProductCategory(category_id="local_2", name="Phones", parent_id="local_1"),
        ]

        mappings = engine.push_categories(adapter, cats)

        assert len(mappings) == 2
        assert mappings[0].local_id == "local_1"
        assert mappings[0].name == "Electronics"
        # Second category should have resolved parent_id
        assert adapter.created_categories[1][1] == mappings[0].remote_id

    def test_push_skips_existing_mappings(self):
        adapter = _MockFullAdapter()
        engine = ProductSyncEngine()
        cats = [ProductCategory(category_id="local_1", name="Already Synced")]

        mappings = engine.push_categories(adapter, cats, existing_mappings={"local_1": "remote_1"})

        assert len(mappings) == 0
        assert len(adapter.created_categories) == 0

    def test_push_raises_without_capability(self):
        adapter = _MockShopAdapter()
        engine = ProductSyncEngine()

        with pytest.raises(TypeError):
            engine.push_categories(adapter, [])
