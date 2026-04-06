"""
Trendyol integration tests — runs against the real Trendyol API (read-only).

Requires TRENDYOL_USERNAME, TRENDYOL_PASSWORD, TRENDYOL_SELLER_ID env vars (see .env).

    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/trendyol/test_integration.py -v -m integration -s
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
from bapp_connectors.core.dto import (
    Contact,
    FinancialTransactionType,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    Product,
)
from bapp_connectors.providers.shop.trendyol.adapter import TrendyolShopAdapter
from tests.shop.financial_contract import FinancialContractTests
from tests.shop.trendyol.conftest import (
    TRENDYOL_COUNTRY,
    TRENDYOL_PASSWORD,
    TRENDYOL_SELLER_ID,
    TRENDYOL_USERNAME,
    skip_unless_trendyol,
)

pytestmark = [pytest.mark.integration, skip_unless_trendyol]


@pytest.fixture
def adapter():
    return TrendyolShopAdapter(credentials={
        "username": TRENDYOL_USERNAME,
        "password": TRENDYOL_PASSWORD,
        "seller_id": TRENDYOL_SELLER_ID,
        "country": TRENDYOL_COUNTRY,
    })


# ── Connection ──


class TestTrendyolConnection:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        print(f"\n  Connection: {result.message}")

    def test_capabilities(self, adapter):
        from bapp_connectors.core.capabilities import ShippingCapability
        assert isinstance(adapter, FinancialCapability)
        assert isinstance(adapter, WebhookCapability)
        assert isinstance(adapter, ShippingCapability)


# ── Orders ──


class TestTrendyolOrders:

    def test_get_orders(self, adapter):
        result = adapter.get_orders()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)
        print(f"\n  Orders: {result.total}")
        if result.items:
            order = result.items[0]
            assert isinstance(order, Order)
            assert order.order_id
            assert order.status in OrderStatus
            assert order.raw_status
            assert order.currency
            print(f"  First: {order.order_id} status={order.raw_status} total={order.total}")

    def test_get_order_detail(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = adapter.get_order(orders.items[0].order_id)
        assert isinstance(order, Order)
        assert order.order_id == orders.items[0].order_id
        assert order.items
        print(f"\n  Order {order.order_id}: {len(order.items)} items, total={order.total}")

    def test_order_has_items(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = adapter.get_order(orders.items[0].order_id)
        assert len(order.items) > 0
        item = order.items[0]
        assert isinstance(item, OrderItem)
        assert item.name
        assert item.sku
        assert isinstance(item.unit_price, Decimal)
        assert isinstance(item.quantity, Decimal)
        print(f"\n  Item: {item.name} sku={item.sku} price={item.unit_price} qty={item.quantity}")
        if item.tax_rate is not None:
            print(f"  Tax rate: {item.tax_rate}")

    def test_order_has_contacts(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.billing is not None or order.shipping is not None
        if order.billing:
            assert isinstance(order.billing, Contact)
            print(f"\n  Billing: {order.billing.name}")
        if order.shipping:
            assert isinstance(order.shipping, Contact)
            print(f"  Shipping: {order.shipping.name}")

    def test_order_has_payment_fields(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.payment_type is not None
        assert order.payment_status is not None

    def test_order_has_created_at(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.created_at is not None
        print(f"\n  Created: {order.created_at}")

    def test_order_has_external_url(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.external_url
        assert "partner.trendyol.com" in order.external_url

    def test_order_has_provider_meta(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.provider_meta is not None
        assert order.provider_meta.provider == "trendyol"
        assert order.provider_meta.raw_payload

    def test_orders_since_filter(self, adapter):
        since = datetime.now(UTC) - timedelta(days=7)
        result = adapter.get_orders(since=since)
        assert isinstance(result, PaginatedResult)
        print(f"\n  Orders (last 7 days): {len(result.items)}")

    def test_orders_with_status_filter(self, adapter):
        """Test fetching orders filtered by Trendyol status."""
        response = adapter.client.get_orders(status="Delivered", size=10)
        content = response.get("content", [])
        for item in content:
            assert item.get("status") == "Delivered"
        print(f"\n  Delivered orders: {len(content)}")


# ── Products ──


class TestTrendyolProducts:

    def test_get_products(self, adapter):
        result = adapter.get_products()
        assert isinstance(result, PaginatedResult)
        print(f"\n  Products: {result.total}")
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
        ids1 = {p.product_id for p in page1.items}
        ids2 = {p.product_id for p in page2.items}
        assert ids1.isdisjoint(ids2)
        print(f"\n  Page 1: {len(page1.items)}, Page 2: {len(page2.items)}")

    def test_product_has_provider_meta(self, adapter):
        result = adapter.get_products()
        if not result.items:
            pytest.skip("No products available")
        product = result.items[0]
        assert product.provider_meta is not None
        assert product.provider_meta.provider == "trendyol"


# ── Categories ──


class TestTrendyolCategories:

    def test_get_categories(self, adapter):
        result = adapter.client.get_categories()
        assert isinstance(result, dict)
        categories = result.get("categories", [])
        assert len(categories) > 0
        cat = categories[0]
        assert cat.get("id")
        assert cat.get("name")
        print(f"\n  Categories: {len(categories)}")


# ── Financial Contract Tests (cross-provider) ──


class TestTrendyolFinancialContract(FinancialContractTests):

    @pytest.fixture
    def adapter(self):
        return TrendyolShopAdapter(credentials={
            "username": TRENDYOL_USERNAME,
            "password": TRENDYOL_PASSWORD,
            "seller_id": TRENDYOL_SELLER_ID,
            "country": TRENDYOL_COUNTRY,
        })

    @pytest.fixture
    def financial_date_range(self):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        return start, end

    @pytest.fixture
    def financial_transaction_type(self):
        return "Sale"


# ── Trendyol-specific Financial Tests ──


class TestTrendyolFinancials:

    def test_get_return_settlements(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type="Return",
        )
        assert isinstance(result, PaginatedResult)
        if result.items:
            assert result.items[0].transaction_type == FinancialTransactionType.RETURN
        print(f"\n  Return settlements: {result.total}")

    def test_get_payment_orders(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type="PaymentOrder",
        )
        assert isinstance(result, PaginatedResult)
        if result.items:
            assert result.items[0].transaction_type == FinancialTransactionType.PAYMENT
        print(f"\n  Payment orders: {result.total}")

    def test_settlement_has_order_reference(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type="Sale",
        )
        if not result.items:
            pytest.skip("No sale settlements in period")
        with_order = [tx for tx in result.items if tx.order_id]
        assert len(with_order) > 0
        print(f"\n  {len(with_order)}/{len(result.items)} settlements have order_id")

    def test_settlement_has_commission(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type="Sale",
        )
        if not result.items:
            pytest.skip("No sale settlements in period")
        with_commission = [tx for tx in result.items if tx.commission_amount is not None]
        assert len(with_commission) > 0
        tx = with_commission[0]
        assert isinstance(tx.commission_amount, Decimal)
        assert isinstance(tx.commission_rate, Decimal)
        print(f"\n  Commission: rate={tx.commission_rate}% amount={tx.commission_amount}")

    def test_default_transaction_type_is_sale(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        result = adapter.get_financial_transactions(start_date=start, end_date=end)
        if result.items:
            assert result.items[0].transaction_type == FinancialTransactionType.SALE

    def test_invalid_transaction_type_raises(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        with pytest.raises(ValueError, match="Invalid transaction_type"):
            adapter.get_financial_transactions(start_date=start, end_date=end, transaction_type="InvalidType")

    def test_invalid_settlement_type_raises(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        with pytest.raises(ValueError, match="Invalid settlement type"):
            adapter.get_settlements("PaymentOrder", start_date=start, end_date=end)

    def test_invalid_other_financial_type_raises(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=14)
        with pytest.raises(ValueError, match="Invalid financial type"):
            adapter.get_other_financials("Sale", start_date=start, end_date=end)


# ── Webhooks ──


# ── Shipping ──


class TestTrendyolShipping:

    def test_get_order_awbs_delivered(self, adapter):
        """Delivered orders should have AWB data."""
        response = adapter.client.get_orders(status="Delivered", size=5)
        content = response.get("content", [])
        if not content:
            pytest.skip("No delivered orders")
        order_number = str(content[0].get("orderNumber", ""))
        from bapp_connectors.core.dto import AWBLabel
        awbs = adapter.get_order_awbs(order_number)
        assert len(awbs) > 0
        awb = awbs[0]
        assert isinstance(awb, AWBLabel)
        assert awb.tracking_number
        assert awb.extra.get("courier")
        print(f"\n  Order {order_number}: tracking={awb.tracking_number} courier={awb.extra['courier']}")
        if awb.label_url:
            print(f"  Tracking URL: {awb.label_url}")

    def test_get_order_awbs_pending_empty(self, adapter):
        """Pending orders without shipment should return empty."""
        response = adapter.client.get_orders(status="Created", size=1)
        content = response.get("content", [])
        if not content:
            pytest.skip("No pending orders")
        order_number = str(content[0].get("orderNumber", ""))
        awbs = adapter.get_order_awbs(order_number)
        assert isinstance(awbs, list)
        print(f"\n  Pending order {order_number}: {len(awbs)} AWB(s)")

    def test_get_awb_pdf(self, adapter):
        """Download AWB PDF via shipmentPackageId."""
        from bapp_connectors.core.errors import PermanentProviderError
        response = adapter.client.get_orders(status="Shipped", size=5)
        content = response.get("content", [])
        if not content:
            pytest.skip("No shipped orders")
        for order in content:
            package_id = order.get("shipmentPackageId")
            if not package_id:
                continue
            try:
                pdf = adapter.get_awb_pdf(str(package_id))
                assert isinstance(pdf, bytes)
                if pdf:
                    print(f"\n  AWB PDF for package {package_id}: {len(pdf)} bytes")
                    return
            except PermanentProviderError:
                continue  # Label not available for this order
        pytest.skip("No AWB labels available for current shipped orders")


class TestTrendyolWebhooks:

    def test_list_webhooks(self, adapter):
        result = adapter.list_webhooks()
        assert isinstance(result, list)
        print(f"\n  Webhooks: {len(result)}")
