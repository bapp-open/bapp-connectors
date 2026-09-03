"""sync_categories passes local_id only to adapters that opt in."""

from __future__ import annotations

from bapp_connectors.core.capabilities import CategoryManagementCapability
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult, ProductCategory
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.sync import ProductSyncEngine


class _CategoryAdapter(ShopPort, CategoryManagementCapability):
    manifest = None  # type: ignore

    def __init__(self):
        self.calls: list[dict] = []

    def validate_credentials(self) -> bool:
        return True

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(success=True)

    def get_orders(self, since=None, cursor=None):
        return PaginatedResult(items=[])

    def get_order(self, order_id):
        raise NotImplementedError

    def get_products(self, cursor=None, since=None):
        return PaginatedResult(items=[])

    def update_product_stock(self, product_id, quantity):
        raise NotImplementedError

    def update_product_price(self, product_id, price, currency):
        raise NotImplementedError

    def update_order_status(self, order_id, status):
        raise NotImplementedError

    def get_categories(self) -> list[ProductCategory]:
        return []

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        self.calls.append({"name": name, "parent_id": parent_id})
        return ProductCategory(category_id=f"remote_{len(self.calls)}", name=name, parent_id=parent_id)


class _LocalIdAdapter(_CategoryAdapter):
    accepts_local_category_id = True

    def create_category(self, name: str, parent_id: str | None = None, local_id: str | None = None) -> ProductCategory:
        self.calls.append({"name": name, "parent_id": parent_id, "local_id": local_id})
        return ProductCategory(category_id=f"remote_{len(self.calls)}", name=name, parent_id=parent_id)


def test_capability_default_is_false():
    assert CategoryManagementCapability.accepts_local_category_id is False


def test_default_adapter_is_called_without_local_id():
    adapter = _CategoryAdapter()
    cats = [ProductCategory(category_id="loc_1", name="Doors")]

    result = ProductSyncEngine().sync_categories(adapter, cats)

    assert adapter.calls == [{"name": "Doors", "parent_id": None}]
    assert result.created[0].local_id == "loc_1"
    assert result.created[0].remote_id == "remote_1"


def test_opted_in_adapter_receives_local_id_and_remote_parent():
    adapter = _LocalIdAdapter()
    cats = [
        ProductCategory(category_id="loc_1", name="Doors"),
        ProductCategory(category_id="loc_2", name="Interior", parent_id="loc_1"),
    ]

    result = ProductSyncEngine().sync_categories(adapter, cats)

    assert adapter.calls == [
        {"name": "Doors", "parent_id": None, "local_id": "loc_1"},
        {"name": "Interior", "parent_id": "remote_1", "local_id": "loc_2"},
    ]
    assert [m.remote_id for m in result.created] == ["remote_1", "remote_2"]
