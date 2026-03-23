"""Tests for TrendyolShopAdapter."""

import json
from pathlib import Path

import responses

from bapp_connectors.core.capabilities import BulkUpdateCapability, InvoiceAttachmentCapability
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.trendyol import TrendyolShopAdapter

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASE_URL = "https://apigw.trendyol.com/integration/"


def _create_adapter():
    return TrendyolShopAdapter(
        credentials={"username": "test", "password": "test", "seller_id": "12345", "country": "RO"},
    )


def test_adapter_implements_ports():
    adapter = _create_adapter()
    assert isinstance(adapter, ShopPort)
    assert isinstance(adapter, BulkUpdateCapability)
    assert isinstance(adapter, InvoiceAttachmentCapability)


def test_adapter_supports_capabilities():
    adapter = _create_adapter()
    assert adapter.supports(BulkUpdateCapability)
    assert adapter.supports(InvoiceAttachmentCapability)


def test_validate_credentials():
    adapter = _create_adapter()
    assert adapter.validate_credentials() is True


def test_validate_credentials_missing():
    adapter = TrendyolShopAdapter(credentials={"username": "test"})
    assert adapter.validate_credentials() is False


@responses.activate
def test_test_connection_success():
    responses.add(
        responses.GET,
        f"{BASE_URL}webhook/sellers/12345/webhooks",
        json={"webhooks": []},
        status=200,
    )
    adapter = _create_adapter()
    result = adapter.test_connection()
    assert result.success is True


@responses.activate
def test_test_connection_failure():
    responses.add(
        responses.GET,
        f"{BASE_URL}webhook/sellers/12345/webhooks",
        json={"error": "Unauthorized"},
        status=401,
    )
    adapter = _create_adapter()
    result = adapter.test_connection()
    assert result.success is False


@responses.activate
def test_get_orders():
    fixture = json.loads((FIXTURES_DIR / "orders_response.json").read_text())
    responses.add(
        responses.GET,
        f"{BASE_URL}order/sellers/12345/orders",
        json=fixture,
        status=200,
    )
    adapter = _create_adapter()
    result = adapter.get_orders()
    assert len(result.items) == 1
    assert result.items[0].order_id == "ORD-12345"


@responses.activate
def test_get_products():
    responses.add(
        responses.GET,
        f"{BASE_URL}product/sellers/12345/products",
        json={
            "content": [
                {
                    "productMainId": "P1",
                    "barcode": "B1",
                    "title": "Test",
                    "salePrice": 10,
                    "quantity": 5,
                    "archived": False,
                }
            ],
            "totalPages": 1,
            "totalElements": 1,
            "page": 0,
            "size": 100,
        },
        status=200,
    )
    adapter = _create_adapter()
    result = adapter.get_products()
    assert len(result.items) == 1
    assert result.items[0].name == "Test"


@responses.activate
def test_update_product_stock():
    responses.add(
        responses.POST,
        f"{BASE_URL}inventory/sellers/12345/products/price-and-inventory",
        json={"batchRequestId": "batch-1"},
        status=200,
    )
    adapter = _create_adapter()
    adapter.update_product_stock("B1", 100)
    assert len(responses.calls) == 1
