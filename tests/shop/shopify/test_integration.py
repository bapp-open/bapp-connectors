"""
Shopify integration tests — runs against a mock Shopify server.

Unlike WooCommerce/PrestaShop, Shopify doesn't have a Docker image.
These tests use a lightweight mock server that simulates the Shopify Admin REST API.

The mock server starts automatically as a pytest fixture — no Docker needed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import (
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductUpdate,
    ProductVariant,
)

MOCK_PORT = 8899


@pytest.fixture(scope="module")
def mock_server():
    """Start the Shopify mock server for the test module."""
    from tests.mocks.shopify_mock import start_mock_server
    server = start_mock_server(MOCK_PORT)
    yield server
    server.shutdown()


@pytest.fixture
def adapter(mock_server):
    from tests.mocks.shopify_mock import _reset
    _reset()  # clean state per test

    from bapp_connectors.providers.shop.shopify.adapter import ShopifyShopAdapter
    return ShopifyShopAdapter(
        credentials={
            "store_domain": f"127.0.0.1:{MOCK_PORT}",
            "access_token": "test_token",
        },
        config={
            "api_version": "2024-01",
            "prices_include_vat": False,
        },
    )


@pytest.fixture
def _override_https(adapter):
    """Override HTTPS to HTTP for mock server."""
    adapter.client.http.base_url = adapter.client.http.base_url.replace("https://", "http://")
    return adapter


@pytest.fixture(autouse=True)
def use_http(adapter):
    """All tests use HTTP for the mock server."""
    adapter.client.http.base_url = adapter.client.http.base_url.replace("https://", "http://")


# ── Contract Tests ──


class TestShopifyContract:
    from tests.shop.contract import ShopContractTests

    for _name, _method in vars(ShopContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Products ──


class TestShopifyProducts:

    def test_get_products_returns_seeded_product(self, adapter):
        result = adapter.get_products()
        assert len(result.items) >= 1
        assert result.items[0].name == "Seed Product"

    def test_create_product(self, adapter):
        created = adapter.create_product(Product(
            product_id="",
            name=f"Shopify Test {uuid.uuid4().hex[:6]}",
            sku="SH-001",
            price=Decimal("25.00"),
            active=True,
        ))
        assert created.product_id
        assert "Shopify Test" in created.name

        products = adapter.get_products()
        ids = [p.product_id for p in products.items]
        assert created.product_id in ids

    def test_update_product(self, adapter):
        created = adapter.create_product(Product(
            product_id="",
            name="To Update",
            price=Decimal("10.00"),
        ))
        adapter.update_product(ProductUpdate(
            product_id=created.product_id,
            name="Updated Name",
        ))

    def test_delete_product(self, adapter):
        created = adapter.create_product(Product(
            product_id="",
            name="To Delete",
            price=Decimal("5.00"),
        ))
        adapter.delete_product(created.product_id)
        products = adapter.get_products()
        assert created.product_id not in [p.product_id for p in products.items]

    def test_bulk_update(self, adapter):
        from bapp_connectors.core.dto import BulkResult
        p1 = adapter.create_product(Product(product_id="", name="Bulk1", price=Decimal("10")))
        p2 = adapter.create_product(Product(product_id="", name="Bulk2", price=Decimal("20")))

        result = adapter.bulk_update_products([
            ProductUpdate(product_id=p1.product_id, name="Bulk1 Updated"),
            ProductUpdate(product_id=p2.product_id, name="Bulk2 Updated"),
        ])
        assert isinstance(result, BulkResult)
        assert result.succeeded == 2
        assert result.failed == 0


# ── Variants ──


class TestShopifyVariants:

    def test_get_variants(self, adapter):
        products = adapter.get_products()
        if products.items:
            variants = adapter.get_variants(products.items[0].product_id)
            assert isinstance(variants, list)
            assert len(variants) >= 1

    def test_create_and_delete_variant(self, adapter):
        product = adapter.create_product(Product(
            product_id="", name="Variable Product", price=Decimal("10"),
        ))

        variant = adapter.create_variant(product.product_id, ProductVariant(
            variant_id="",
            sku="VAR-001",
            price=Decimal("15.00"),
            attributes={"option1": "Large"},
        ))
        assert variant.variant_id

        variants = adapter.get_variants(product.product_id)
        assert len(variants) >= 2  # default + new

        adapter.delete_variant(product.product_id, variant.variant_id)


# ── Orders ──


class TestShopifyOrders:

    def test_get_orders(self, adapter):
        result = adapter.get_orders()
        assert isinstance(result, PaginatedResult)
        assert len(result.items) >= 1

    def test_order_has_raw_status(self, adapter):
        result = adapter.get_orders()
        for order in result.items:
            assert isinstance(order, Order)
            assert order.raw_status is not None


# ── Webhooks ──


class TestShopifyWebhooks:

    def test_register_and_list_webhooks(self, adapter):
        result = adapter.register_webhook(
            url="https://example.com/webhook",
            events=["orders/create"],
        )
        assert len(result["webhooks"]) == 1
        webhook_id = result["webhooks"][0].get("id")

        webhooks = adapter.list_webhooks()
        assert any(w.get("id") == webhook_id for w in webhooks)

    def test_verify_webhook(self, adapter):
        import base64
        import hashlib
        import hmac
        body = b'{"id": 123}'
        secret = "test_secret"
        sig = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()

        adapter._webhook_secret = secret
        assert adapter.verify_webhook({"X-Shopify-Hmac-Sha256": sig}, body) is True
        assert adapter.verify_webhook({"X-Shopify-Hmac-Sha256": "invalid"}, body) is False

    def test_parse_webhook(self, adapter):
        from bapp_connectors.core.dto import WebhookEvent, WebhookEventType
        body = b'{"id": 456, "title": "Test"}'
        headers = {"X-Shopify-Topic": "products/create", "X-Shopify-Webhook-Id": "wh-123"}
        event = adapter.parse_webhook(headers, body)
        assert isinstance(event, WebhookEvent)
        assert event.event_type == WebhookEventType.PRODUCT_CREATED


# ── Sync Engine ──


class TestShopifySyncEngine:

    def test_pull_products(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine
        engine = ProductSyncEngine()
        received = []
        result = engine.pull_products(adapter, on_product=received.append)
        assert result.updated >= 1
        assert result.failed == 0

    def test_push_creates_product(self, adapter):
        from bapp_connectors.core.sync import ProductSyncEngine
        engine = ProductSyncEngine()
        product = Product(
            product_id="local_1",
            name=f"Sync Test {uuid.uuid4().hex[:6]}",
            price=Decimal("12.00"),
            active=True,
        )
        result = engine.push_products(adapter, [product])
        assert result.created == 1


# ── Errors ──


# ── Pagination ──


class TestShopifyPagination:

    def test_get_products_pagination(self, adapter):
        # Create enough products to paginate with limit=2
        for i in range(3):
            adapter.create_product(Product(
                product_id="", name=f"Page Test {i}", price=Decimal("10"),
            ))
        # Fetch with small limit via client directly
        page1 = adapter.client.get_products(limit=2)
        assert len(page1) == 2
        cursor = str(page1[-1]["id"])
        page2 = adapter.client.get_products(limit=2, since_id=int(cursor))
        assert len(page2) >= 1
        # IDs on page2 should all be greater than cursor
        assert all(p["id"] > int(cursor) for p in page2)

    def test_get_products_returns_cursor_when_has_more(self, adapter):
        from bapp_connectors.providers.shop.shopify.mappers import products_from_shopify
        # Seed 3 products, use limit=2 to trigger has_more
        for i in range(3):
            adapter.create_product(Product(
                product_id="", name=f"Cursor Test {i}", price=Decimal("5"),
            ))
        response = adapter.client.get_products(limit=2)
        result = products_from_shopify(response, limit=2)
        assert result.has_more is True
        assert result.cursor is not None

    def test_get_products_no_more_when_under_limit(self, adapter):
        # Only seed data exists (1 product), limit=250 >> 1
        result = adapter.get_products()
        assert result.has_more is False
        assert result.cursor is None

    def test_get_orders_returns_cursor_when_has_more(self, adapter):
        from bapp_connectors.providers.shop.shopify.mappers import orders_from_shopify
        # Only 1 seeded order, use limit=1 to trigger has_more
        response = adapter.client.get_orders(limit=1)
        result = orders_from_shopify(response, limit=1)
        assert result.has_more is True
        assert result.cursor is not None


# ── Categories (Collections) ──


class TestShopifyCategories:

    def test_get_categories_returns_both_types(self, adapter):
        from bapp_connectors.core.dto import ProductCategory
        categories = adapter.get_categories()
        assert isinstance(categories, list)
        # Should include seeded smart collection
        assert any(c.name == "Sale Items" for c in categories)
        for c in categories:
            assert isinstance(c, ProductCategory)
            assert c.category_id

    def test_create_category(self, adapter):
        category = adapter.create_category("Summer Collection")
        assert category.category_id
        assert category.name == "Summer Collection"
        assert category.extra.get("collection_type") == "custom"

    def test_created_category_appears_in_list(self, adapter):
        adapter.create_category("Winter Collection")
        categories = adapter.get_categories()
        assert any(c.name == "Winter Collection" for c in categories)

    def test_smart_collection_has_correct_type(self, adapter):
        categories = adapter.get_categories()
        smart = [c for c in categories if c.name == "Sale Items"]
        assert len(smart) == 1
        assert smart[0].extra.get("collection_type") == "smart"


# ── Order Cancellation ──


class TestShopifyOrderCancellation:

    def test_cancel_order(self, adapter):
        result = adapter.get_orders()
        assert result.items
        order = result.items[0]
        cancelled = adapter.update_order_status(order.external_id, OrderStatus.CANCELLED)
        assert isinstance(cancelled, Order)

    def test_unsupported_status_raises_value_error(self, adapter):
        result = adapter.get_orders()
        order = result.items[0]
        with pytest.raises(ValueError, match="does not support"):
            adapter.update_order_status(order.external_id, OrderStatus.SHIPPED)


# ── OAuth ──


class TestShopifyOAuth:

    def test_get_authorize_url(self):
        from bapp_connectors.providers.shop.shopify.adapter import ShopifyShopAdapter
        adapter = ShopifyShopAdapter(credentials={
            "store_domain": "myshop.myshopify.com",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        })
        url = adapter.get_authorize_url("https://example.com/callback", state="abc123")
        assert "myshop.myshopify.com/admin/oauth/authorize" in url
        assert "client_id=test_client_id" in url
        assert "redirect_uri=https" in url
        assert "state=abc123" in url
        assert "scope=" in url

    def test_oauth_capability_declared_in_manifest(self):
        from bapp_connectors.core.capabilities import OAuthCapability
        from bapp_connectors.providers.shop.shopify.manifest import manifest
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Shopify"
        assert len(manifest.auth.oauth.credential_fields) == 3
        assert len(manifest.auth.oauth.scopes) > 0

    def test_refresh_token_raises(self):
        from bapp_connectors.providers.shop.shopify.adapter import ShopifyShopAdapter
        adapter = ShopifyShopAdapter(credentials={"store_domain": "test.myshopify.com"})
        with pytest.raises(NotImplementedError):
            adapter.refresh_token("some_token")


# ── Errors ──


class TestShopifyErrors:

    def test_missing_credentials(self):
        from bapp_connectors.providers.shop.shopify.adapter import ShopifyShopAdapter
        adapter = ShopifyShopAdapter(credentials={})
        assert adapter.validate_credentials() is False
