"""Tests for Trendyol DTO mappers."""

import json
from decimal import Decimal
from pathlib import Path

from bapp_connectors.core.dto import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.providers.shop.trendyol.mappers import (
    order_from_trendyol,
    orders_from_trendyol,
    product_from_trendyol,
    products_from_trendyol,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def test_order_from_trendyol():
    data = _load_fixture("orders_response.json")["content"][0]
    order = order_from_trendyol(data)

    assert order.order_id == "ORD-12345"
    assert order.external_id == "999"
    assert order.status == OrderStatus.PENDING
    assert order.payment_status == PaymentStatus.UNPAID
    assert order.payment_type == PaymentType.ONLINE_CARD
    assert order.currency == "TRY"
    assert len(order.items) == 1
    assert order.items[0].name == "Test Product"
    assert order.items[0].sku == "SKU-001"
    assert order.items[0].quantity == Decimal("2")
    assert order.items[0].unit_price == Decimal("49.99")
    assert order.billing is not None
    assert order.billing.name == "John Doe"
    assert order.billing.phone == "+90555123456"
    assert order.shipping_address is not None
    assert order.shipping_address.city == "Istanbul"
    assert order.created_at is not None
    assert order.provider_meta is not None
    assert order.provider_meta.provider == "trendyol"


def test_orders_from_trendyol_pagination():
    data = _load_fixture("orders_response.json")
    result = orders_from_trendyol(data)

    assert len(result.items) == 1
    assert result.has_more is False
    assert result.cursor is None
    assert result.total == 1


def test_order_status_mapping():
    for trendyol_status, expected in [
        ("Created", OrderStatus.PENDING),
        ("Picking", OrderStatus.PROCESSING),
        ("Shipped", OrderStatus.SHIPPED),
        ("Delivered", OrderStatus.DELIVERED),
        ("Cancelled", OrderStatus.CANCELLED),
    ]:
        data = {"orderNumber": "1", "orderDate": 1700000000000, "status": trendyol_status, "lines": []}
        order = order_from_trendyol(data)
        assert order.status == expected, f"Expected {expected} for {trendyol_status}, got {order.status}"


def test_product_from_trendyol():
    data = {
        "productMainId": "PROD-1",
        "barcode": "8680000001",
        "stockCode": "SKU-001",
        "title": "Test Product",
        "salePrice": 99.99,
        "listPrice": 119.99,
        "quantity": 50,
        "archived": False,
        "approved": True,
    }
    product = product_from_trendyol(data)

    assert product.product_id == "PROD-1"
    assert product.barcode == "8680000001"
    assert product.sku == "SKU-001"
    assert product.name == "Test Product"
    assert product.price == Decimal("99.99")
    assert product.stock == 50
    assert product.active is True


def test_products_from_trendyol_pagination():
    response = {
        "content": [
            {"productMainId": "1", "barcode": "B1", "title": "P1", "salePrice": 10, "quantity": 5, "archived": False},
            {"productMainId": "2", "barcode": "B2", "title": "P2", "salePrice": 20, "quantity": 10, "archived": False},
        ],
        "totalPages": 3,
        "totalElements": 6,
        "page": 0,
        "size": 2,
    }
    result = products_from_trendyol(response)

    assert len(result.items) == 2
    assert result.has_more is True
    assert result.cursor == "1"  # next page
    assert result.total == 6
