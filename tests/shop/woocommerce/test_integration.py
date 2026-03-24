"""
WooCommerce integration tests — runs against WordPress + WooCommerce in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d
    python scripts/setup_woocommerce.py
    uv run --extra dev pytest tests/shop/woocommerce/ -v -m integration
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import (
    Order,
    OrderStatus,
    PaginatedResult,
    PaymentType,
    Product,
    WebhookEvent,
    WebhookEventType,
)
from tests.shop.conftest import (
    WOO_CONSUMER_KEY,
    WOO_CONSUMER_SECRET,
    WOO_HOST,
    WOO_PORT,
    skip_unless_woo,
)

pytestmark = [pytest.mark.integration, skip_unless_woo]


@pytest.fixture
def adapter():
    from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter

    return WooCommerceShopAdapter(
        credentials={
            "consumer_key": WOO_CONSUMER_KEY,
            "consumer_secret": WOO_CONSUMER_SECRET,
            "domain": f"http://{WOO_HOST}:{WOO_PORT}",
            "verify_ssl": "false",
        },
        config={
            "prices_include_vat": False,
            "use_query_auth": True,  # Required for WooCommerce 10.x over HTTP (avoids PHP 8.3 bug)
        },
    )


@pytest.fixture
def test_product(adapter):
    """Create a test product and clean it up after the test."""
    product_data = {
        "name": "Integration Test Product",
        "type": "simple",
        "regular_price": "19.99",
        "sku": "INT-TEST-001",
        "manage_stock": True,
        "stock_quantity": 10,
        "status": "publish",
        "description": "A test product for integration testing",
        "categories": [{"name": "Test Category"}],
    }
    created = adapter.client.create_product(product_data)
    product_id = str(created.get("id", ""))
    yield product_id, created
    adapter.client.delete_product(product_id)


# ── Contract Tests ──


class TestWooCommerceContract:
    """Run the shop contract suite against WooCommerce."""

    from tests.shop.contract import ShopContractTests

    for _name, _method in vars(ShopContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Product CRUD ──


class TestWooCommerceProducts:

    def test_create_product_shows_in_list(self, adapter, test_product):
        product_id, _ = test_product
        result = adapter.get_products()
        product_ids = [p.product_id for p in result.items]
        assert product_id in product_ids

    def test_product_dto_has_correct_fields(self, adapter, test_product):
        product_id, raw = test_product
        result = adapter.get_products()
        product = next(p for p in result.items if p.product_id == product_id)

        assert isinstance(product, Product)
        assert product.name == "Integration Test Product"
        assert product.sku == "INT-TEST-001"
        assert product.stock == 10
        assert product.active is True
        assert product.price == Decimal("19.99")

    def test_product_has_categories(self, adapter, test_product):
        product_id, _ = test_product
        result = adapter.get_products()
        product = next(p for p in result.items if p.product_id == product_id)
        assert len(product.categories) > 0

    def test_product_photos_are_list(self, adapter, test_product):
        product_id, _ = test_product
        result = adapter.get_products()
        product = next(p for p in result.items if p.product_id == product_id)
        assert isinstance(product.photos, list)

    def test_update_stock(self, adapter, test_product):
        product_id, _ = test_product
        adapter.update_product_stock(product_id, 42)

        updated = adapter.client.get_product(product_id)
        assert updated.get("stock_quantity") == 42

    def test_update_price(self, adapter, test_product):
        product_id, _ = test_product
        adapter.update_product_price(product_id, Decimal("29.99"), "RON")

        updated = adapter.client.get_product(product_id)
        assert updated.get("regular_price") == "29.99"

    def test_update_stock_to_zero(self, adapter, test_product):
        product_id, _ = test_product
        adapter.update_product_stock(product_id, 0)

        updated = adapter.client.get_product(product_id)
        assert updated.get("stock_quantity") == 0


# ── Order Mapping ──


class TestWooCommerceOrders:

    def test_get_orders_empty_store(self, adapter):
        result = adapter.get_orders()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    def test_get_order_by_id(self, adapter, test_product):
        """Create an order via raw API, then fetch it via adapter."""
        product_id, _ = test_product
        raw_order = adapter.client.http.call("POST", "orders", json={
            "payment_method": "bacs",
            "status": "processing",
            "billing": {
                "first_name": "Test",
                "last_name": "User",
                "address_1": "123 Test St",
                "city": "Bucharest",
                "country": "RO",
                "postcode": "010101",
                "email": "test@test.com",
                "phone": "0700000000",
            },
            "line_items": [{"product_id": int(product_id), "quantity": 2}],
        })
        order_id = str(raw_order.get("id", ""))

        try:
            order = adapter.get_order(order_id)
            assert isinstance(order, Order)
            assert order.order_id
            assert order.status == OrderStatus.PENDING  # "processing" maps to PENDING
            assert order.total > 0
            assert order.currency == "RON"
            assert len(order.items) == 1
            assert order.items[0].quantity == Decimal("2")
        finally:
            adapter.client.http.call("DELETE", f"orders/{order_id}", params={"force": "true"})

    def test_order_has_billing_contact(self, adapter, test_product):
        product_id, _ = test_product
        raw_order = adapter.client.http.call("POST", "orders", json={
            "billing": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john@example.com",
                "phone": "0711111111",
                "address_1": "Str Libertatii 1",
                "city": "Cluj-Napoca",
                "state": "CJ",
                "postcode": "400001",
                "country": "RO",
                "company": "Test SRL",
            },
            "line_items": [{"product_id": int(product_id), "quantity": 1}],
        })
        order_id = str(raw_order["id"])

        try:
            order = adapter.get_order(order_id)
            assert order.billing is not None
            assert order.billing.name == "John Doe"
            assert order.billing.email == "john@example.com"
            assert order.billing.phone == "0711111111"
            assert order.billing.company_name == "Test SRL"
            assert order.billing.address is not None
            assert order.billing.address.city == "Cluj-Napoca"
            assert order.billing.address.country == "RO"
        finally:
            adapter.client.http.call("DELETE", f"orders/{order_id}", params={"force": "true"})

    def test_order_status_mapping(self, adapter, test_product):
        product_id, _ = test_product
        statuses = {
            "pending": OrderStatus.PENDING,
            "processing": OrderStatus.PENDING,
            "completed": OrderStatus.DELIVERED,
            "cancelled": OrderStatus.CANCELLED,
        }
        for woo_status, expected_status in statuses.items():
            raw = adapter.client.http.call("POST", "orders", json={
                "status": woo_status,
                "line_items": [{"product_id": int(product_id), "quantity": 1}],
            })
            order_id = str(raw["id"])
            try:
                order = adapter.get_order(order_id)
                assert order.status == expected_status, f"WooCommerce '{woo_status}' should map to {expected_status}, got {order.status}"
            finally:
                adapter.client.http.call("DELETE", f"orders/{order_id}", params={"force": "true"})

    def test_order_payment_type_mapping(self, adapter, test_product):
        product_id, _ = test_product
        raw = adapter.client.http.call("POST", "orders", json={
            "payment_method": "cod",
            "line_items": [{"product_id": int(product_id), "quantity": 1}],
        })
        order_id = str(raw["id"])
        try:
            order = adapter.get_order(order_id)
            assert order.payment_type == PaymentType.CASH_ON_DELIVERY
        finally:
            adapter.client.http.call("DELETE", f"orders/{order_id}", params={"force": "true"})

    def test_get_orders_since_filter(self, adapter):
        from datetime import datetime, timedelta
        future = datetime.now() + timedelta(days=1)
        result = adapter.get_orders(since=future)
        assert len(result.items) == 0


# ── Webhook Verification ──


class TestWooCommerceWebhooks:

    def test_verify_webhook_valid_signature(self, adapter):
        body = json.dumps({"id": 123, "status": "processing"}).encode()
        signature = base64.b64encode(
            hmac.new(WOO_CONSUMER_SECRET.encode(), body, hashlib.sha256).digest()
        ).decode()

        assert adapter.verify_webhook(
            headers={"X-WC-Webhook-Signature": signature},
            body=body,
        ) is True

    def test_verify_webhook_invalid_signature(self, adapter):
        body = b'{"id": 123}'
        assert adapter.verify_webhook(
            headers={"X-WC-Webhook-Signature": "invalid_signature"},
            body=body,
        ) is False

    def test_verify_webhook_missing_signature(self, adapter):
        assert adapter.verify_webhook(headers={}, body=b"{}") is False

    def test_parse_webhook_order_created(self, adapter):
        body = json.dumps({"id": 456, "status": "processing", "total": "99.99"}).encode()
        headers = {
            "X-WC-Webhook-Topic": "order.created",
            "X-WC-Webhook-Resource": "order",
            "X-WC-Webhook-ID": "1",
            "X-WC-Webhook-Delivery-ID": "delivery-abc",
        }
        event = adapter.parse_webhook(headers, body)
        assert isinstance(event, WebhookEvent)
        assert event.event_type == WebhookEventType.ORDER_CREATED
        assert event.provider == "woocommerce"
        assert event.payload["id"] == 456
        assert event.idempotency_key == "delivery-abc"

    def test_parse_webhook_product_updated(self, adapter):
        body = json.dumps({"id": 789, "name": "Updated Product"}).encode()
        headers = {
            "X-WC-Webhook-Topic": "product.updated",
            "X-WC-Webhook-Resource": "product",
            "X-WC-Webhook-ID": "2",
            "X-WC-Webhook-Delivery-ID": "delivery-xyz",
        }
        event = adapter.parse_webhook(headers, body)
        assert event.event_type == WebhookEventType.PRODUCT_UPDATED

    # ── Live API webhook CRUD ──

    def test_register_and_list_webhooks(self, adapter):
        """Register a webhook via API, verify it appears in list, then delete."""
        # Use a dummy URL — WooCommerce accepts it, just won't deliver
        result = adapter.register_webhook(
            url="https://example.com/webhook/test",
            events=["order.created"],
        )
        assert "webhooks" in result
        assert len(result["webhooks"]) == 1
        webhook_id = result["webhooks"][0].get("id")
        assert webhook_id

        try:
            # Verify it shows in list
            webhooks = adapter.list_webhooks()
            webhook_ids = [w.get("id") for w in webhooks]
            assert webhook_id in webhook_ids

            # Verify webhook fields
            wh = next(w for w in webhooks if w["id"] == webhook_id)
            assert wh["topic"] == "order.created"
            assert wh["delivery_url"] == "https://example.com/webhook/test"
            assert wh["status"] == "active"
        finally:
            adapter.client.delete_webhook(webhook_id)

    def test_list_webhooks_empty(self, adapter):
        """List webhooks on a clean store."""
        webhooks = adapter.list_webhooks()
        assert isinstance(webhooks, list)

    def test_register_multiple_webhooks(self, adapter):
        """Register multiple event types at once."""
        result = adapter.register_webhook(
            url="https://example.com/webhook/multi",
            events=["order.created", "order.updated"],
        )
        assert len(result["webhooks"]) == 2
        ids = [w["id"] for w in result["webhooks"]]

        try:
            webhooks = adapter.list_webhooks()
            listed_ids = [w["id"] for w in webhooks]
            for wid in ids:
                assert wid in listed_ids
        finally:
            for wid in ids:
                adapter.client.delete_webhook(wid)


# ── Attributes ──


class TestWooCommerceAttributes:
    """Attribute CRUD tests. Note: create/write tests may fail on WooCommerce 10.x
    with PHP 8.3 due to a WC bug (preg_match on WP_REST_Request). Read tests work."""

    @pytest.mark.xfail(reason="WooCommerce 10.x PHP 8.3 bug in attribute controller", strict=False)
    def test_create_and_get_attribute(self, adapter):
        from bapp_connectors.core.dto import AttributeDefinition, AttributeValue

        attr = adapter.create_attribute(AttributeDefinition(
            attribute_id="",
            name=f"Test Color {uuid.uuid4().hex[:6]}",
            attribute_type="select",
            values=[
                AttributeValue(name="Red"),
                AttributeValue(name="Blue"),
            ],
        ))
        try:
            assert attr.attribute_id
            assert len(attr.values) == 2

            # Fetch it back
            fetched = adapter.get_attribute(attr.attribute_id)
            assert fetched.name == attr.name
            assert len(fetched.values) == 2
        finally:
            adapter.delete_attribute(attr.attribute_id)

    def test_list_attributes(self, adapter):
        from bapp_connectors.core.dto import AttributeDefinition

        attrs = adapter.get_attributes()
        assert isinstance(attrs, list)
        for a in attrs:
            assert isinstance(a, AttributeDefinition)

    @pytest.mark.xfail(reason="WooCommerce 10.x PHP 8.3 bug in attribute controller", strict=False)
    def test_add_attribute_value(self, adapter):
        from bapp_connectors.core.dto import AttributeDefinition, AttributeValue

        attr = adapter.create_attribute(AttributeDefinition(
            attribute_id="",
            name=f"Test Size {uuid.uuid4().hex[:6]}",
            values=[AttributeValue(name="S")],
        ))
        try:
            new_val = adapter.add_attribute_value(attr.attribute_id, AttributeValue(name="XL"))
            assert new_val.name == "XL"
            assert new_val.value_id

            fetched = adapter.get_attribute(attr.attribute_id)
            val_names = [v.name for v in fetched.values]
            assert "S" in val_names
            assert "XL" in val_names
        finally:
            adapter.delete_attribute(attr.attribute_id)


# ── Variants ──


class TestWooCommerceVariants:

    @pytest.mark.xfail(reason="WooCommerce 10.x PHP 8.3 bug in attribute controller (variant test depends on attribute creation)", strict=False)
    def test_create_variable_product_with_variations(self, adapter):
        from bapp_connectors.core.dto import (
            AttributeDefinition,
            AttributeValue,
            Product,
            ProductAttribute,
            ProductVariant,
        )

        # 1. Create attribute
        attr = adapter.create_attribute(AttributeDefinition(
            attribute_id="",
            name=f"Var Color {uuid.uuid4().hex[:6]}",
            values=[AttributeValue(name="Red"), AttributeValue(name="Blue")],
        ))

        try:
            # 2. Create variable product with attribute
            product = adapter.create_product(Product(
                product_id="",
                name=f"Variable Product {uuid.uuid4().hex[:6]}",
                sku=f"VAR-{uuid.uuid4().hex[:6]}",
                price=Decimal("10.00"),
                attributes=[ProductAttribute(
                    attribute_id=attr.attribute_id,
                    attribute_name=attr.name,
                    values=["Red", "Blue"],
                    used_for_variants=True,
                    visible=True,
                )],
            ))

            try:
                # 3. Create variations
                var_red = adapter.create_variant(product.product_id, ProductVariant(
                    variant_id="",
                    sku=f"VAR-RED-{uuid.uuid4().hex[:6]}",
                    price=Decimal("12.00"),
                    stock=5,
                    attributes={attr.name: "Red"},
                ))
                assert var_red.variant_id

                var_blue = adapter.create_variant(product.product_id, ProductVariant(
                    variant_id="",
                    sku=f"VAR-BLUE-{uuid.uuid4().hex[:6]}",
                    price=Decimal("14.00"),
                    stock=3,
                    attributes={attr.name: "Blue"},
                ))
                assert var_blue.variant_id

                # 4. Get variants
                variants = adapter.get_variants(product.product_id)
                assert len(variants) == 2
                variant_skus = [v.sku for v in variants]
                assert var_red.sku in variant_skus
                assert var_blue.sku in variant_skus

                # 5. Update variant
                updated = adapter.update_variant(product.product_id, ProductVariant(
                    variant_id=var_red.variant_id,
                    price=Decimal("15.00"),
                    stock=10,
                ))
                assert updated.stock == 10

                # 6. Delete variant
                adapter.delete_variant(product.product_id, var_blue.variant_id)
                remaining = adapter.get_variants(product.product_id)
                assert len(remaining) == 1

            finally:
                adapter.delete_product(product.product_id)
        finally:
            adapter.delete_attribute(attr.attribute_id)


# ── Related Products ──


class TestWooCommerceRelatedProducts:

    def test_get_related_products(self, adapter, test_product):
        from bapp_connectors.core.dto import RelatedProductLink

        links = adapter.get_related_products(test_product[0])
        assert isinstance(links, list)
        for link in links:
            assert isinstance(link, RelatedProductLink)

    def test_set_upsell_products(self, adapter):
        from bapp_connectors.core.dto import Product, RelatedProductLink

        # Create two products
        p1 = adapter.create_product(Product(product_id="", name=f"Main {uuid.uuid4().hex[:6]}", price=Decimal("10")))
        p2 = adapter.create_product(Product(product_id="", name=f"Upsell {uuid.uuid4().hex[:6]}", price=Decimal("20")))
        try:
            adapter.set_related_products(p1.product_id, [
                RelatedProductLink(product_id=p2.product_id, link_type="upsell"),
            ])

            links = adapter.get_related_products(p1.product_id)
            upsell_ids = [l.product_id for l in links if l.link_type == "upsell"]
            assert p2.product_id in upsell_ids
        finally:
            adapter.delete_product(p1.product_id)
            adapter.delete_product(p2.product_id)


# ── Error Handling ──


class TestWooCommerceErrors:

    def test_unreachable_host_fails_connection(self):
        from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter

        adapter = WooCommerceShopAdapter(credentials={
            "consumer_key": "ck_invalid",
            "consumer_secret": "cs_invalid",
            "domain": "http://127.0.0.1:19999",
            "verify_ssl": "false",
        })
        result = adapter.test_connection()
        assert result.success is False

    def test_missing_credentials_validation(self):
        from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter

        adapter = WooCommerceShopAdapter(credentials={})
        assert adapter.validate_credentials() is False


# ── Sync Engine Integration ──


class TestWooCommerceSyncEngine:
    """Test ProductSyncEngine against a live WooCommerce instance."""

    def test_pull_products(self, adapter, test_product):
        """Pull products and verify the test product is included."""
        from bapp_connectors.core.sync import ProductSyncEngine

        product_id, _ = test_product
        engine = ProductSyncEngine()

        received = []
        result = engine.pull_products(adapter, on_product=received.append)

        assert result.updated >= 1
        assert result.failed == 0
        product_ids = [p.product_id for p in received]
        assert product_id in product_ids

    def test_push_creates_product(self, adapter):
        """Push a new product via sync engine and verify it was created."""
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        product = Product(
            product_id="local_sync_test",
            name="Sync Engine Test Product",
            sku="SYNC-TEST-001",
            price=Decimal("15.50"),
            stock=7,
            active=True,
        )

        result = engine.push_products(adapter, [product])
        assert result.created == 1
        assert result.failed == 0

        # Verify it exists on WooCommerce
        try:
            remote = adapter.get_products()
            names = [p.name for p in remote.items]
            assert "Sync Engine Test Product" in names
            # Get the remote ID for cleanup
            remote_product = next(p for p in remote.items if p.name == "Sync Engine Test Product")
            adapter.delete_product(remote_product.product_id)
        except Exception:
            pass

    def test_push_updates_existing_product(self, adapter, test_product):
        """Push an update to an existing product via sync engine."""
        from bapp_connectors.core.sync import ProductSyncEngine

        product_id, _ = test_product
        engine = ProductSyncEngine()

        product = Product(
            product_id="local_1",
            name="Updated via Sync Engine",
            price=Decimal("99.99"),
            stock=42,
        )

        def match(p):
            return product_id

        result = engine.push_products(adapter, [product], match_fn=match)
        assert result.updated == 1

        # Verify the update on WooCommerce
        updated = adapter.client.get_product(product_id)
        assert updated.get("name") == "Updated via Sync Engine"

    def test_push_skips_without_match(self, adapter, test_product):
        """Push with match_fn returning None + product that needs creation counts as created."""
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        product = Product(product_id="new_one", name="Brand New", price=Decimal("5.00"))

        result = engine.push_products(adapter, [product], match_fn=lambda p: None)
        assert result.created == 1

        # Cleanup
        remote = adapter.get_products()
        for p in remote.items:
            if p.name == "Brand New":
                adapter.delete_product(p.product_id)
                break


class TestWooCommerceCategorySync:
    """Test category sync against a live WooCommerce instance."""

    def test_pull_categories(self, adapter):
        """Pull categories from WooCommerce."""
        from bapp_connectors.core.dto import ProductCategory

        categories = adapter.get_categories()
        assert isinstance(categories, list)
        for cat in categories:
            assert isinstance(cat, ProductCategory)
            assert cat.category_id
            assert cat.name

    def test_create_and_pull_category(self, adapter):
        """Create a category, verify it shows in pull."""

        cat_name = f"Sync Test {uuid.uuid4().hex[:8]}"
        created = adapter.create_category(cat_name)
        assert created.category_id
        assert cat_name in created.name

        try:
            categories = adapter.get_categories()
            cat_names = [c.name for c in categories]
            assert cat_name in cat_names
        finally:
            adapter.client.http.call(
                "DELETE", f"products/categories/{created.category_id}",
                params={"force": "true"},
            )

    def test_create_category_with_parent(self, adapter):
        """Create a parent + child category."""
        parent_name = f"Parent {uuid.uuid4().hex[:8]}"
        child_name = f"Child {uuid.uuid4().hex[:8]}"
        parent = adapter.create_category(parent_name)
        try:
            child = adapter.create_category(child_name, parent_id=parent.category_id)
            try:
                assert child.parent_id == parent.category_id
            finally:
                adapter.client.http.call("DELETE", f"products/categories/{child.category_id}", params={"force": "true"})
        finally:
            adapter.client.http.call("DELETE", f"products/categories/{parent.category_id}", params={"force": "true"})

    def test_push_categories_via_engine(self, adapter):
        """Push categories via the sync engine and verify mappings."""
        from bapp_connectors.core.dto import ProductCategory
        from bapp_connectors.core.sync import ProductSyncEngine

        parent_name = f"Engine Parent {uuid.uuid4().hex[:8]}"
        child_name = f"Engine Child {uuid.uuid4().hex[:8]}"
        engine = ProductSyncEngine()
        categories = [
            ProductCategory(category_id="local_parent", name=parent_name),
            ProductCategory(category_id="local_child", name=child_name, parent_id="local_parent"),
        ]

        mappings = engine.push_categories(adapter, categories)
        assert len(mappings) == 2
        assert mappings[0].local_id == "local_parent"
        assert mappings[1].local_id == "local_child"

        try:
            remote_cats = adapter.get_categories()
            remote_names = [c.name for c in remote_cats]
            assert parent_name in remote_names
            assert child_name in remote_names
        finally:
            for m in reversed(mappings):
                adapter.client.http.call("DELETE", f"products/categories/{m.remote_id}", params={"force": "true"})

    def test_push_categories_skips_existing(self, adapter):
        """Push categories with existing mappings — should skip them."""
        from bapp_connectors.core.dto import ProductCategory
        from bapp_connectors.core.sync import ProductSyncEngine

        engine = ProductSyncEngine()
        categories = [ProductCategory(category_id="already_mapped", name="Should Skip")]

        mappings = engine.push_categories(adapter, categories, existing_mappings={"already_mapped": "remote_99"})
        assert len(mappings) == 0


class TestWooCommerceProductCreation:
    """Test ProductCreationCapability against live WooCommerce."""

    def test_create_product_returns_product_dto(self, adapter):
        """create_product returns a Product DTO with the remote ID."""
        created = adapter.create_product(Product(
            product_id="ignored",
            name="Creation Test Product",
            sku="CREATE-001",
            price=Decimal("25.00"),
            stock=3,
            active=True,
        ))

        try:
            assert isinstance(created, Product)
            assert created.product_id  # should be WooCommerce's ID
            assert created.name == "Creation Test Product"
        finally:
            adapter.delete_product(created.product_id)

    def test_create_product_with_categories(self, adapter):
        """Create a category first, then a product assigned to it."""
        cat = adapter.create_category("Product Test Category")
        try:
            # Create product using category ID in extra (WooCommerce needs IDs, not names)
            created = adapter.client.create_product({
                "name": "Categorized Product",
                "regular_price": "10.00",
                "categories": [{"id": int(cat.category_id)}],
            })
            product_id = str(created["id"])
            try:
                remote = adapter.client.get_product(product_id)
                cat_names = [c["name"] for c in remote.get("categories", [])]
                assert "Product Test Category" in cat_names
            finally:
                adapter.delete_product(product_id)
        finally:
            adapter.client.http.call("DELETE", f"products/categories/{cat.category_id}", params={"force": "true"})

    def test_delete_product(self, adapter):
        """Create then delete a product."""
        created = adapter.create_product(Product(
            product_id="ignored",
            name="To Be Deleted",
            price=Decimal("1.00"),
        ))

        adapter.delete_product(created.product_id)

        # Verify it's gone
        products = adapter.get_products()
        assert created.product_id not in [p.product_id for p in products.items]

    def test_full_update_product(self, adapter, test_product):
        """Test ProductFullUpdateCapability.update_product with all fields."""
        from bapp_connectors.core.dto import ProductUpdate

        product_id, _ = test_product
        adapter.update_product(ProductUpdate(
            product_id=product_id,
            name="Fully Updated Product",
            description="New description",
            price=Decimal("55.55"),
            stock=99,
            active=True,
            categories=["Updated Category"],
        ))

        updated = adapter.client.get_product(product_id)
        assert updated["name"] == "Fully Updated Product"
        assert "New description" in updated.get("description", "")
        assert updated["stock_quantity"] == 99
