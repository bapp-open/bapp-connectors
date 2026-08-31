"""Pure mapper tests — no Docker, no network."""
from decimal import Decimal

from bapp_connectors.core.dto import Product, ProductPhoto, ProductUpdate
from bapp_connectors.providers.shop.woocommerce.mappers import (
    product_to_woocommerce,
    product_update_to_woocommerce,
)


def test_create_payload_uses_category_ids_not_names():
    product = Product(product_id="1", name="Ciocan", categories=["Scule"], category_ids=["12", "7"])
    data = product_to_woocommerce(product)
    assert data["categories"] == [{"id": 12}, {"id": 7}]


def test_create_payload_without_category_ids_sends_no_categories():
    product = Product(product_id="1", name="Ciocan", categories=["Scule"])
    assert "categories" not in product_to_woocommerce(product)


def test_update_payload_category_ids_none_leaves_categories_untouched():
    update = ProductUpdate(product_id="5", name="X")
    assert "categories" not in product_update_to_woocommerce(update)


def test_update_payload_empty_category_ids_clears_categories():
    update = ProductUpdate(product_id="5", category_ids=[])
    assert product_update_to_woocommerce(update)["categories"] == []


def test_update_payload_maps_price_and_photos():
    update = ProductUpdate(
        product_id="5", price=Decimal("10.00"),
        photos=[ProductPhoto(url="https://cdn/x.jpg", position=0, alt_text="x")],
    )
    data = product_update_to_woocommerce(update, price_to_provider=lambda p: p * Decimal("1.19"))
    assert data["regular_price"] == "11.9000"
    assert data["images"] == [{"src": "https://cdn/x.jpg", "alt": "x", "position": 0}]
