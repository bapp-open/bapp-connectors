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
    PaginatedResult,
    Product,
    ProductUpdate,
    ProductVariant,
)

MOCK_PORT = 8899


@pytest.fixture(scope="module")
def mock_server():
    """Start the Shopify mock server for the test module."""
    from tests.mocks.shopify_mock import start_mock_server, _reset
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
        import base64, hashlib, hmac
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


class TestShopifyErrors:

    def test_missing_credentials(self):
        from bapp_connectors.providers.shop.shopify.adapter import ShopifyShopAdapter
        adapter = ShopifyShopAdapter(credentials={})
        assert adapter.validate_credentials() is False
