"""
Okazii integration tests — runs against the real Okazii API (read-only).

Requires OKAZII_TOKEN env var (see .env).

    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/okazii/test_integration.py -v -m integration -s
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bapp_connectors.core.capabilities import InvoiceAttachmentCapability
from bapp_connectors.core.dto import (
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
)
from bapp_connectors.providers.shop.okazii.adapter import OkaziiShopAdapter
from tests.shop.okazii.conftest import OKAZII_TOKEN, skip_unless_okazii

pytestmark = [pytest.mark.integration, skip_unless_okazii]


@pytest.fixture
def adapter():
    return OkaziiShopAdapter(credentials={"token": OKAZII_TOKEN})


# ── Connection ──


class TestOkaziiConnection:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        print(f"\n  Connection: {result.message}")

    def test_capabilities(self, adapter):
        from bapp_connectors.core.capabilities import ShippingCapability
        assert isinstance(adapter, InvoiceAttachmentCapability)
        assert isinstance(adapter, ShippingCapability)


# ── Orders ──


class TestOkaziiOrders:

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
        assert order.order_id
        print(f"\n  Order {order.order_id}: {len(order.items)} items, total={order.total}")

    def test_order_has_items(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = adapter.get_order(orders.items[0].order_id)
        if not order.items:
            pytest.skip("Order has no items")
        item = order.items[0]
        assert isinstance(item, OrderItem)
        assert item.item_id or item.product_id
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
        if order.shipping:
            print(f"  Shipping: {order.shipping.name}")

    def test_order_has_provider_meta(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        order = orders.items[0]
        assert order.provider_meta is not None
        assert order.provider_meta.provider == "okazii"
        assert order.provider_meta.raw_payload

    def test_orders_since_filter(self, adapter):
        since = datetime.now(UTC) - timedelta(days=30)
        result = adapter.get_orders(since=since)
        assert isinstance(result, PaginatedResult)
        print(f"\n  Orders (last 30 days): {len(result.items)}")

    def test_order_invoices(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        result = adapter.client.get_order_invoices(orders.items[0].order_id)
        assert result is not None
        print(f"\n  Invoices for order {orders.items[0].order_id}: {type(result).__name__}")


# ── Couriers ──


class TestOkaziiCouriers:

    def test_get_couriers(self, adapter):
        couriers = adapter.client.get_couriers()
        assert isinstance(couriers, list)
        assert len(couriers) > 0
        print(f"\n  Couriers: {len(couriers)}")
        for c in couriers[:5]:
            print(f"    {c.get('name', c.get('identifier', ''))}")

    def test_get_order_courier(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        result = adapter.client.get_order_courier(orders.items[0].order_id)
        assert result is not None
        print(f"\n  AWB for order {orders.items[0].order_id}: {type(result).__name__}")


# ── ShippingCapability ──


class TestOkaziiShipping:

    def test_get_order_awbs(self, adapter):
        orders = adapter.get_orders()
        if not orders.items:
            pytest.skip("No orders available")
        # Find an order with shipment data
        for order in orders.items:
            awbs = adapter.get_order_awbs(order.order_id)
            if awbs:
                from bapp_connectors.core.dto import AWBLabel
                assert isinstance(awbs[0], AWBLabel)
                assert awbs[0].tracking_number
                print(f"\n  Order {order.order_id}: {len(awbs)} AWB(s)")
                for awb in awbs:
                    print(f"    tracking={awb.tracking_number} courier={awb.extra.get('courier')} status={awb.extra.get('status')}")
                return
        pytest.skip("No orders with AWBs found")

    def test_get_order_awbs_not_found_raises(self, adapter):
        """Non-existent order should raise an error."""
        from bapp_connectors.core.errors import PermanentProviderError
        with pytest.raises(PermanentProviderError):
            adapter.get_order_awbs("999999999")

    def test_get_awb_pdf(self, adapter):
        orders = adapter.get_orders()
        for order in orders.items:
            awbs = adapter.get_order_awbs(order.order_id)
            if awbs:
                pdf = adapter.get_awb_pdf(awbs[0].tracking_number)
                assert isinstance(pdf, bytes)
                assert len(pdf) > 0
                assert pdf[:5] == b"%PDF-"
                print(f"\n  AWB PDF for {awbs[0].tracking_number}: {len(pdf)} bytes")
                return
        pytest.skip("No orders with AWBs found")


# ── GDL AWB ──


class TestOkaziiGdlAwb:

    def _find_awb_code(self, adapter):
        """Find a GDL AWB code from existing orders."""
        orders = adapter.get_orders()
        for order in orders.items:
            for bid in order.provider_meta.raw_payload.get("bids", []):
                shipment = bid.get("shipment", {})
                if shipment.get("awbCode") and shipment.get("awbType") == "okazii":
                    return shipment["awbCode"]
        return None

    def test_get_gdl_awb(self, adapter):
        awb_code = self._find_awb_code(adapter)
        if not awb_code:
            pytest.skip("No GDL AWB found in orders")
        result = adapter.client.get_gdl_awb(awb_code)
        assert isinstance(result, dict)
        assert result.get("code") == awb_code
        shipment = result.get("shipment", {})
        assert shipment.get("awbCode") == awb_code
        print(f"\n  GDL AWB {awb_code}: courier={shipment.get('courier')} status={shipment.get('status')}")

    def test_get_gdl_awb_pdf(self, adapter):
        awb_code = self._find_awb_code(adapter)
        if not awb_code:
            pytest.skip("No GDL AWB found in orders")
        pdf = adapter.client.get_gdl_awb_pdf(awb_code)
        assert isinstance(pdf, bytes)
        assert len(pdf) > 0
        assert pdf[:5] == b"%PDF-"
        print(f"\n  GDL AWB PDF: {len(pdf)} bytes")


# ── Location ──


class TestOkaziiLocation:

    def test_get_countries(self, adapter):
        result = adapter.client.get_countries()
        assert result
        if isinstance(result, dict):
            members = result.get("hydra:member", [])
            print(f"\n  Countries: {len(members)}")
            for c in members[:5]:
                print(f"    {c.get('code', '')} = {c.get('name', '')}")
        else:
            print(f"\n  Countries response: {type(result).__name__}")

    def test_get_counties(self, adapter):
        counties = adapter.client.get_counties()
        assert isinstance(counties, list)
        assert len(counties) > 0
        print(f"\n  Counties: {len(counties)}")
        for c in counties[:5]:
            print(f"    {c.get('code', '')} = {c.get('name', '')}")

    def test_get_cities(self, adapter):
        cities = adapter.client.get_cities()
        assert isinstance(cities, list)
        assert len(cities) > 0
        print(f"\n  Cities: {len(cities)}")
        for c in cities[:5]:
            print(f"    {c.get('id', '')} = {c.get('name', '')}")
