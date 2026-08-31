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
    PaginatedResult,
    Product,
    ProductCategory,
    ProductPhoto,
    ProductUpdate,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.sync import ProductSyncEngine

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


from bapp_connectors.core.capabilities import BulkUpsertCapability
from bapp_connectors.core.dto import BulkItemResult, BulkUpsertResult


class _MockBulkAdapter(_MockFullAdapter, BulkUpsertCapability):
    max_batch_size = 100

    def __init__(self, *args, fail_create_index=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.batches: list[tuple[list[Product], list[ProductUpdate]]] = []
        self._fail_create_index = fail_create_index

    def bulk_upsert_products(self, creates, updates):
        self.batches.append((list(creates), list(updates)))
        created = []
        for i, p in enumerate(creates):
            if self._fail_create_index == i and len(self.batches) == 1:
                created.append(BulkItemResult(index=i, error="SKU exists", error_code="product_invalid_sku", extra={"resource_id": 77}))
            else:
                created.append(BulkItemResult(index=i, remote_id=f"r{p.product_id}", extra={"date_modified_gmt": "2026-08-31T00:00:00"}))
        updated = [BulkItemResult(index=i, remote_id=u.product_id) for i, u in enumerate(updates)]
        return BulkUpsertResult(created=created, updated=updated)

    def update_category(self, category):
        self.updated_categories = getattr(self, "updated_categories", [])
        self.updated_categories.append(category)
        return category


class TestPushProductsBulk:
    def _products(self, n):
        return [Product(product_id=str(i), name=f"P{i}", sku=f"S{i}") for i in range(n)]

    def test_batches_by_batch_size_and_pauses_between(self):
        adapter = _MockBulkAdapter()
        sleeps = []
        result = ProductSyncEngine().push_products(adapter, self._products(5), batch_size=2, pause_seconds=1.5, sleep=sleeps.append)
        assert [len(c) for c, _ in adapter.batches] == [2, 2, 1]
        assert sleeps == [1.5, 1.5]  # no pause before the first batch
        assert result.created == 5 and result.failed == 0
        assert result.remote_ids["3"] == "r3"
        assert result.remote_meta["3"]["date_modified_gmt"] == "2026-08-31T00:00:00"

    def test_splits_creates_and_updates_using_match_fn(self):
        adapter = _MockBulkAdapter()
        products = self._products(3)
        result = ProductSyncEngine().push_products(adapter, products, match_fn=lambda p: "remote9" if p.product_id == "1" else None, batch_size=10)
        creates, updates = adapter.batches[0]
        assert [p.product_id for p in creates] == ["0", "2"]
        assert updates[0].product_id == "remote9" and updates[0].name == "P1"
        assert result.created == 2 and result.updated == 1
        assert result.remote_ids["1"] == "remote9"

    def test_positional_error_is_reported_for_the_right_product(self):
        adapter = _MockBulkAdapter(fail_create_index=1)
        result = ProductSyncEngine().push_products(adapter, self._products(3), batch_size=10)
        assert result.created == 2 and result.failed == 1
        err = result.errors[0]
        assert err.product_id == "1" and err.code == "product_invalid_sku" and err.extra["resource_id"] == 77
        assert "1" not in result.remote_ids

    def test_batch_exception_fails_every_item_of_that_batch_only(self):
        class _Boom(_MockBulkAdapter):
            def bulk_upsert_products(self, creates, updates):
                if len(self.batches) == 0:
                    self.batches.append((creates, updates))
                    raise RuntimeError("502")
                return super().bulk_upsert_products(creates, updates)

        result = ProductSyncEngine().push_products(_Boom(), self._products(4), batch_size=2)
        assert result.failed == 2 and result.created == 2

    def test_batch_size_is_capped_by_adapter_max(self):
        adapter = _MockBulkAdapter()
        adapter.max_batch_size = 3
        ProductSyncEngine().push_products(adapter, self._products(7), batch_size=50)
        assert [len(c) for c, _ in adapter.batches] == [3, 3, 1]


class TestSequentialPushRemoteIds:
    def test_sequential_create_records_remote_id(self):
        adapter = _MockFullAdapter()
        result = ProductSyncEngine().push_products(adapter, [Product(product_id="7", name="X")])
        assert result.remote_ids["7"] == "remote_7"


class TestSyncCategories:
    def test_updates_existing_when_name_or_parent_differs(self):
        adapter = _MockBulkAdapter()
        cats = [ProductCategory(category_id="1", name="Scule"), ProductCategory(category_id="2", name="Electrice", parent_id="1")]
        remote = {"r1": ProductCategory(category_id="r1", name="Scule"), "r2": ProductCategory(category_id="r2", name="Electric", parent_id="r1")}
        result = ProductSyncEngine().sync_categories(adapter, cats, existing_mappings={"1": "r1", "2": "r2"}, update_existing=True, remote_categories=remote)
        assert result.created == []
        assert result.updated == ["2"]
        sent = adapter.updated_categories[0]
        assert sent.category_id == "r2" and sent.name == "Electrice" and sent.parent_id == "r1"

    def test_no_update_without_remote_snapshot_when_flag_off(self):
        adapter = _MockBulkAdapter()
        cats = [ProductCategory(category_id="1", name="Scule")]
        result = ProductSyncEngine().sync_categories(adapter, cats, existing_mappings={"1": "r1"})
        assert result.updated == [] and not getattr(adapter, "updated_categories", [])

    def test_push_categories_still_returns_created_list(self):
        adapter = _MockFullAdapter()
        created = ProductSyncEngine().push_categories(adapter, [ProductCategory(category_id="1", name="A")])
        assert created[0].local_id == "1" and created[0].remote_id == "remote_cat_1"
