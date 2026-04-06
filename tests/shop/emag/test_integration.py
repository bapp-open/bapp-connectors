"""
eMAG integration tests — runs against the real eMAG API (read-only).

Requires EMAG_USERNAME, EMAG_PASSWORD env vars (see .env).

    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/emag/test_integration.py -v -m integration -s
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
from bapp_connectors.core.dto import (
    Contact,
    FinancialInvoice,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    Product,
)
from bapp_connectors.providers.shop.emag.adapter import EmagShopAdapter
from tests.shop.emag.conftest import (
    EMAG_COUNTRY,
    EMAG_PASSWORD,
    EMAG_USERNAME,
    skip_unless_emag,
)
from tests.shop.financial_contract import FinancialContractTests, InvoiceContractTests

pytestmark = [pytest.mark.integration, skip_unless_emag]


@pytest.fixture
def adapter():
    return EmagShopAdapter(credentials={
        "username": EMAG_USERNAME,
        "password": EMAG_PASSWORD,
        "country": EMAG_COUNTRY,
    })


# ── Connection ──


class TestEmagConnection:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        print(f"\n  Connection: {result.message}")

    def test_capabilities(self, adapter):
        assert isinstance(adapter, FinancialCapability)
        assert isinstance(adapter, WebhookCapability)


# ── Orders ──


class TestEmagOrders:

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
        assert item.item_id
        assert isinstance(item.unit_price, Decimal)
        assert isinstance(item.quantity, Decimal)
        # eMAG product name may be in item.name or item.extra["name"]
        name = item.name or item.extra.get("name", "")
        print(f"\n  Item: {name} sku={item.sku} price={item.unit_price} qty={item.quantity}")

    def test_order_has_billing_contact(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.billing is not None
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

    def test_order_has_raw_status(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.raw_status, "raw_status should preserve original provider status"

    def test_order_has_created_at(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.created_at is not None
        print(f"\n  Created: {order.created_at}")

    def test_order_has_provider_meta(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.provider_meta is not None
        assert order.provider_meta.provider == "emag"
        assert order.provider_meta.raw_payload

    def test_order_has_external_url(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.external_url
        assert "emag" in order.external_url
        print(f"\n  URL: {order.external_url}")

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

    def test_orders_since_filter(self, adapter):
        since = datetime.now(UTC) - timedelta(days=7)
        result = adapter.get_orders(since=since)
        assert isinstance(result, PaginatedResult)
        print(f"\n  Orders (last 7 days): {len(result.items)}")


# ── Products ──


class TestEmagProducts:

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
        print(f"\n  Page 1: {len(page1.items)}, Page 2: {len(page2.items)}")

    def test_product_has_provider_meta(self, adapter):
        result = adapter.get_products()
        if not result.items:
            pytest.skip("No products available")
        product = result.items[0]
        assert product.provider_meta is not None
        assert product.provider_meta.provider == "emag"


# ── Categories ──


class TestEmagCategories:

    def test_get_categories(self, adapter):
        result = adapter.client.get_categories()
        assert result.results is not None
        assert len(result.results) > 0
        cat = result.results[0]
        assert cat.get("id")
        assert cat.get("name")
        print(f"\n  Categories: {len(result.results)}")


# ── Reference Data ──


class TestEmagReferenceData:

    def test_get_vat_rates(self, adapter):
        result = adapter.client.get_vat_list()
        assert result.results is not None
        assert len(result.results) > 0
        vat = result.results[0]
        assert "vat_id" in vat or "vat_rate" in vat
        print(f"\n  VAT rates: {len(result.results)}")

    def test_get_couriers(self, adapter):
        result = adapter.client.get_couriers()
        assert result.results is not None
        print(f"\n  Couriers: {len(result.results)}")
        for c in result.results[:3]:
            print(f"    {c.get('courier_name', '')} (account_id={c.get('account_id')})")

    def test_get_locality(self, adapter):
        result = adapter.client.get_locality(region="Bucuresti", name="Bucuresti")
        assert result.results is not None
        assert len(result.results) > 0
        loc = result.results[0]
        assert loc.get("name")
        print(f"\n  Locality: {loc.get('name')} (emag_id={loc.get('emag_id')})")


# ── Invoice Categories ──


class TestEmagInvoiceCategories:

    def test_get_invoice_categories(self, adapter):
        result = adapter.client.get_invoice_categories()
        categories = result.get("results", [])
        assert len(categories) > 0
        cat_codes = [c["category"] for c in categories]
        assert "FC" in cat_codes
        print(f"\n  {len(categories)} invoice categories")


# ── Financial Contract Tests (cross-provider) ──


class TestEmagFinancialContract(FinancialContractTests):

    @pytest.fixture
    def adapter(self):
        return EmagShopAdapter(credentials={
            "username": EMAG_USERNAME,
            "password": EMAG_PASSWORD,
            "country": EMAG_COUNTRY,
        })

    @pytest.fixture
    def financial_date_range(self):
        end = datetime.now(UTC)
        start = end - timedelta(days=90)
        return start, end


class TestEmagInvoiceContract(InvoiceContractTests):

    @pytest.fixture
    def adapter(self):
        return EmagShopAdapter(credentials={
            "username": EMAG_USERNAME,
            "password": EMAG_PASSWORD,
            "country": EMAG_COUNTRY,
        })


# ── eMAG-specific Financial Tests ──


class TestEmagInvoices:

    def test_get_invoices_by_category(self, adapter):
        result = adapter.get_invoices(category="FC")
        assert isinstance(result, PaginatedResult)
        print(f"\n  FC invoices: {result.total}")
        for inv in result.items:
            assert inv.category.startswith("FC")

    def test_get_invoices_by_date_range(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=90)
        result = adapter.get_invoices(start_date=start, end_date=end)
        assert isinstance(result, PaginatedResult)
        print(f"\n  Invoices (last 90 days): {result.total}")

    def test_invoices_pagination(self, adapter):
        page1 = adapter.get_invoices()
        if not page1.has_more:
            pytest.skip("Only one page of invoices")
        page2 = adapter.get_invoices(cursor="2")
        assert isinstance(page2, PaginatedResult)
        assert len(page2.items) > 0
        # Different invoices on each page
        nums1 = {inv.invoice_number for inv in page1.items}
        nums2 = {inv.invoice_number for inv in page2.items}
        assert nums1.isdisjoint(nums2)
        print(f"\n  Page 1: {len(page1.items)}, Page 2: {len(page2.items)}")

    def test_invoice_has_currency(self, adapter):
        result = adapter.get_invoices()
        if not result.items:
            pytest.skip("No invoices available")
        inv = result.items[0]
        assert inv.currency
        print(f"\n  Currency: {inv.currency}")

    def test_get_commission_transactions(self, adapter):
        end = datetime.now(UTC)
        start = end - timedelta(days=90)
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type="FC",
        )
        assert isinstance(result, PaginatedResult)
        print(f"\n  Commission transactions: {result.total}")
        for tx in result.items:
            assert tx.raw_transaction_type == "FC"


# ── Customer Invoices ──


class TestEmagCustomerInvoices:

    def test_get_customer_invoices(self, adapter):
        result = adapter.get_customer_invoices()
        assert isinstance(result, PaginatedResult)
        print(f"\n  Customer invoices: {result.total}")
        if result.items:
            inv = result.items[0]
            assert isinstance(inv, FinancialInvoice)
            assert inv.invoice_number
            print(f"  First: {inv.invoice_number} order={inv.order_id}")
