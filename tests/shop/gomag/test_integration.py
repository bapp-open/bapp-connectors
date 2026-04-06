"""
Gomag integration tests — runs against the real Gomag API (read-only).

Requires GOMAG_TOKEN, GOMAG_SHOP_SITE env vars (see .env).

    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/gomag/test_integration.py -v -m integration -s
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
)
from bapp_connectors.core.dto import (
    AttributeDefinition,
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductCategory,
)
from bapp_connectors.providers.shop.gomag.adapter import GomagShopAdapter
from tests.shop.gomag.conftest import (
    GOMAG_SHOP_SITE,
    GOMAG_TOKEN,
    skip_unless_gomag,
)

pytestmark = [pytest.mark.integration, skip_unless_gomag]


@pytest.fixture
def adapter():
    from bapp_connectors.core.http import MultiHeaderAuth, ResilientHttpClient
    from bapp_connectors.core.http.rate_limit import RateLimiter
    from bapp_connectors.core.http.retry import RetryPolicy

    http_client = ResilientHttpClient(
        base_url="https://api.gomag.ro/api/v1/",
        auth=MultiHeaderAuth({
            "ApiShop": GOMAG_SHOP_SITE,
            "Apikey": GOMAG_TOKEN,
            "User-Agent": "BappConnectors/1.0",
            "Accept": "*/*",
        }),
        provider_name="gomag",
        rate_limiter=RateLimiter(requests_per_second=1, burst=2),
        retry_policy=RetryPolicy(max_retries=3, base_delay=5.0),
    )
    return GomagShopAdapter(
        credentials={"token": GOMAG_TOKEN, "shop_site": GOMAG_SHOP_SITE},
        http_client=http_client,
    )


# ── Connection ──


class TestGomagConnection:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        print(f"\n  Connection: {result.message}")

    def test_capabilities(self, adapter):
        assert isinstance(adapter, ProductCreationCapability)
        assert isinstance(adapter, BulkUpdateCapability)
        assert isinstance(adapter, CategoryManagementCapability)
        assert isinstance(adapter, AttributeManagementCapability)


# ── Orders ──


class TestGomagOrders:

    def test_get_orders(self, adapter):
        result = adapter.get_orders()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)
        print(f"\n  Orders: {len(result.items)}")
        if result.items:
            order = result.items[0]
            assert isinstance(order, Order)
            assert order.order_id
            assert order.status in OrderStatus
            assert order.currency
            print(f"  First: {order.order_id} status={order.status} total={order.total}")

    def test_get_order_detail(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = adapter.get_order(orders.items[0].order_id)
        assert isinstance(order, Order)
        assert order.order_id == orders.items[0].order_id
        print(f"\n  Order {order.order_id}: {len(order.items)} items, total={order.total}")

    def test_order_has_items(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = adapter.get_order(orders.items[0].order_id)
        assert len(order.items) > 0
        item = order.items[0]
        assert isinstance(item, OrderItem)
        assert isinstance(item.unit_price, Decimal)
        assert isinstance(item.quantity, Decimal)
        print(f"\n  Item: {item.name} sku={item.sku} price={item.unit_price} qty={item.quantity}")

    def test_order_has_contacts(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.billing is not None or order.shipping is not None
        if order.billing:
            assert isinstance(order.billing, Contact)
            print(f"\n  Billing: {order.billing.name}")

    def test_order_has_payment_fields(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.payment_type is not None
        assert order.payment_status is not None
        print(f"\n  Payment: type={order.payment_type} status={order.payment_status}")

    def test_order_has_provider_meta(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.provider_meta is not None
        assert order.provider_meta.provider == "gomag"
        assert order.provider_meta.raw_payload

    def test_orders_pagination(self, adapter):
        page1 = adapter.get_orders()
        if not page1.has_more:
            pytest.skip("Only one page of orders")
        page2 = adapter.get_orders(cursor=page1.cursor)
        assert isinstance(page2, PaginatedResult)
        assert len(page2.items) > 0
        ids1 = {o.order_id for o in page1.items}
        ids2 = {o.order_id for o in page2.items}
        assert ids1.isdisjoint(ids2)
        print(f"\n  Page 1: {len(page1.items)}, Page 2: {len(page2.items)}")


# ── Products ──


class TestGomagProducts:

    def test_get_products(self, adapter):
        result = adapter.get_products()
        assert isinstance(result, PaginatedResult)
        print(f"\n  Products: {len(result.items)}")
        if result.items:
            product = result.items[0]
            assert isinstance(product, Product)
            assert product.product_id
            assert product.name
            assert isinstance(product.price, Decimal)
            print(f"  First: {product.product_id} - {product.name} price={product.price}")

    def test_products_pagination(self, adapter):
        page1 = adapter.get_products()
        if not page1.has_more:
            pytest.skip("Only one page of products")
        page2 = adapter.get_products(cursor=page1.cursor)
        assert isinstance(page2, PaginatedResult)
        assert len(page2.items) > 0
        print(f"\n  Page 1: {len(page1.items)}, Page 2: {len(page2.items)}")

    def test_product_has_provider_meta(self, adapter):
        result = adapter.get_products()
        if not result.items:
            pytest.skip("No products available")
        product = result.items[0]
        assert product.provider_meta is not None
        assert product.provider_meta.provider == "gomag"


# ── Categories ──


class TestGomagCategories:

    def test_get_categories(self, adapter):
        from bapp_connectors.providers.shop.gomag.mappers import categories_from_gomag
        response = adapter.client.get_categories(page=1, limit=10)
        categories = categories_from_gomag(response)
        assert isinstance(categories, list)
        assert len(categories) > 0
        cat = categories[0]
        assert isinstance(cat, ProductCategory)
        assert cat.category_id
        assert cat.name
        print(f"\n  Categories (first page): {len(categories)}")
        for c in categories[:5]:
            print(f"    {c.category_id} = {c.name}")


# ── Attributes ──


class TestGomagAttributes:

    def test_get_attributes(self, adapter):
        from bapp_connectors.providers.shop.gomag.mappers import attributes_from_gomag
        response = adapter.client.get_attributes(page=1, limit=10)
        attributes = attributes_from_gomag(response)
        assert isinstance(attributes, list)
        assert len(attributes) > 0
        attr = attributes[0]
        assert isinstance(attr, AttributeDefinition)
        assert attr.attribute_id
        assert attr.name
        print(f"\n  Attributes (first page): {len(attributes)}")
        print(f"  First: {attr.attribute_id} = {attr.name}")


# ── Customers ──


class TestGomagCustomers:

    def test_get_customers(self, adapter):
        result = adapter.get_customers()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)
        print(f"\n  Customers: {len(result.items)}")
        if result.items:
            customer = result.items[0]
            assert isinstance(customer, Contact)
            print(f"  First: {customer.name} {customer.email}")


# ── Payment Methods ──


class TestGomagPaymentMethods:

    def test_get_payment_methods(self, adapter):
        methods = adapter.get_payment_methods()
        assert isinstance(methods, list)
        print(f"\n  Payment methods: {len(methods)}")
        for m in methods[:5]:
            print(f"    {m.get('name', m.get('title', ''))}")


# ── Carriers ──


class TestGomagCarriers:

    def test_get_carriers(self, adapter):
        carriers = adapter.get_carriers()
        assert isinstance(carriers, list)
        print(f"\n  Carriers: {len(carriers)}")
        for c in carriers[:5]:
            print(f"    {c.get('name', c.get('carrier_name', ''))}")
