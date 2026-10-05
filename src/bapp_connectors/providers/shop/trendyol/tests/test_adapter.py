"""Tests for TrendyolShopAdapter."""

import json
from pathlib import Path

import responses

from bapp_connectors.core.capabilities import BulkUpdateCapability, InvoiceAttachmentCapability
from bapp_connectors.core.dto import ProductUpdate
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


PRODUCTS_V2_URL = f"{BASE_URL}product/sellers/12345/products/approved"

PRODUCTS_V2_PAGE = {
    "content": [
        {
            "contentId": 9510902,
            "productMainId": "P1",
            "title": "Test",
            "variants": [
                {
                    "barcode": "B1",
                    "stockCode": "S1",
                    "archived": False,
                    "stock": {"quantity": 5},
                    "price": {"salePrice": 10, "listPrice": 12},
                },
                {
                    "barcode": "B2",
                    "stockCode": "S2",
                    "archived": True,
                    "stock": {"quantity": 0},
                    "price": {"salePrice": 11, "listPrice": 13},
                },
            ],
        }
    ],
    "totalPages": 3,
    "totalElements": 250,
    "page": 0,
    "size": 100,
}


@responses.activate
def test_get_products_reads_product_v2_one_item_per_barcode():
    responses.add(responses.GET, PRODUCTS_V2_URL, json=PRODUCTS_V2_PAGE, status=200)
    adapter = _create_adapter()

    result = adapter.get_products()

    assert responses.calls[0].request.params == {"size": "100", "page": "0"}
    assert [(p.barcode, p.sku, p.name, p.price, p.stock, p.active) for p in result.items] == [
        ("B1", "S1", "Test", 10, 5, True),
        ("B2", "S2", "Test", 11, 0, False),
    ]
    assert result.items[0].product_id == "P1"
    assert result.items[0].extra["contentId"] == 9510902
    assert (result.has_more, result.cursor) == (True, "1")


@responses.activate
def test_get_products_continues_with_the_page_token():
    responses.add(responses.GET, PRODUCTS_V2_URL, json={**PRODUCTS_V2_PAGE, "nextPageToken": "tok-1"}, status=200)
    adapter = _create_adapter()

    first = adapter.get_products()
    adapter.get_products(cursor=first.cursor)

    assert first.cursor == "token:tok-1"
    assert responses.calls[1].request.params == {"size": "100", "nextPageToken": "tok-1"}


@responses.activate
def test_get_products_stops_on_the_last_page():
    responses.add(responses.GET, PRODUCTS_V2_URL, json={**PRODUCTS_V2_PAGE, "page": 2}, status=200)

    result = _create_adapter().get_products(cursor="2")

    assert (result.has_more, result.cursor) == (False, None)


@responses.activate
def test_bulk_update_sends_the_name_to_content_and_price_to_inventory():
    responses.add(responses.GET, PRODUCTS_V2_URL, json=PRODUCTS_V2_PAGE, status=200)
    responses.add(
        responses.POST,
        f"{BASE_URL}product/sellers/12345/products/content-bulk-update",
        json={"batchRequestId": "batch-2"},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{BASE_URL}inventory/sellers/12345/products/price-and-inventory",
        json={"batchRequestId": "batch-1"},
        status=200,
    )
    adapter = _create_adapter()

    result = adapter.bulk_update_products(
        [
            ProductUpdate(product_id="B1", name="Nou", stock=7),
            ProductUpdate(product_id="B2", name="Altul", extra={"contentId": 77}),
        ]
    )

    posts = [call.request for call in responses.calls if call.request.method == "POST"]
    lookups = [call.request for call in responses.calls if call.request.method == "GET"]
    bodies = {request.url.rsplit("/", 1)[-1]: json.loads(request.body) for request in posts}
    assert bodies["price-and-inventory"] == {"items": [{"barcode": "B1", "quantity": 7}]}
    assert bodies["content-bulk-update"] == {
        "items": [{"contentId": 9510902, "title": "Nou"}, {"contentId": 77, "title": "Altul"}]
    }
    # only B1 needed the barcode lookup
    assert [request.params["barcode"] for request in lookups] == ["B1"]
    assert (result.succeeded, result.failed) == (2, 0)


@responses.activate
def test_bulk_update_reports_a_name_for_an_unknown_barcode():
    responses.add(responses.GET, PRODUCTS_V2_URL, json={"content": [], "totalPages": 0}, status=200)

    result = _create_adapter().bulk_update_products([ProductUpdate(product_id="NOPE", name="Nou")])

    assert (result.succeeded, result.failed) == (0, 1)
    assert result.errors[0]["barcode"] == "NOPE"


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
