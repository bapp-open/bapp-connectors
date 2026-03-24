"""
Compari.ro mapper unit tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto.product import Product, ProductAttribute, ProductPhoto
from bapp_connectors.providers.feed._utils import format_price_plain
from bapp_connectors.providers.feed.compari.mappers import (
    product_to_feed_item,
    validate_feed_item,
)


@pytest.fixture
def config():
    return {
        "base_url": "https://shop.ro",
        "product_url_template": "{base_url}/produs/{product_id}",
        "currency": "RON",
        "manufacturer_fallback": "DefaultMfg",
        "default_delivery_time": "2-4 zile",
        "default_delivery_cost": "19.99",
    }


@pytest.fixture
def full_product():
    return Product(
        product_id="CP1",
        sku="CSKU1",
        barcode="1111111111111",
        name="Compari Product",
        description="A test product for Compari.ro feed.",
        price=Decimal("150.00"),
        stock=30,
        active=True,
        categories=["Electronice", "Telefoane"],
        photos=[
            ProductPhoto(url="https://shop.ro/img/phone.jpg", position=0),
        ],
        attributes=[
            ProductAttribute(attribute_id="1", attribute_name="Producator", values=["Samsung"]),
        ],
    )


class TestProductToFeedItem:
    def test_basic_mapping(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "CP1",
            "sku": "CSKU1",
            "barcode": "1111111111111",
            "name": "Compari Product",
            "price": Decimal("150.00"),
            "stock": 30,
            "image_url": "https://shop.ro/img/phone.jpg",
        }
        result = product_to_feed_item(full_product, item_data, config)
        assert result.identifier == "CP1"
        assert result.name == "Compari Product"
        assert result.product_url == "https://shop.ro/produs/CP1"
        assert result.price == "150.00"
        assert result.currency == "RON"
        assert result.ean_code == "1111111111111"
        assert result.delivery_time == "2-4 zile"
        assert result.delivery_cost == "19.99"

    def test_manufacturer_from_producator(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "CP1",
            "sku": "CSKU1",
            "barcode": "1111111111111",
            "name": "Compari Product",
            "price": Decimal("150.00"),
            "stock": 30,
            "image_url": "https://shop.ro/img/phone.jpg",
        }
        result = product_to_feed_item(full_product, item_data, config)
        assert result.manufacturer == "Samsung"

    def test_manufacturer_fallback(self, config):
        product = Product(product_id="NM1", name="No Mfg", price=Decimal("25"),
                          categories=["Test"], photos=[ProductPhoto(url="https://x.jpg", position=0)])
        item_data = {
            "product": product,
            "variant": None,
            "item_id": "NM1",
            "sku": None,
            "barcode": None,
            "name": "No Mfg",
            "price": Decimal("25"),
            "stock": None,
            "image_url": "https://x.jpg",
        }
        result = product_to_feed_item(product, item_data, config)
        assert result.manufacturer == "DefaultMfg"

    def test_category_hierarchy(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "CP1",
            "sku": None,
            "barcode": None,
            "name": "Compari Product",
            "price": Decimal("150"),
            "stock": 30,
            "image_url": "https://shop.ro/img/phone.jpg",
        }
        result = product_to_feed_item(full_product, item_data, config)
        assert result.category == "Electronice > Telefoane"


class TestValidateFeedItem:
    def test_valid_item(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "CP1",
            "sku": "CSKU1",
            "barcode": "1111111111111",
            "name": "Compari Product",
            "price": Decimal("150.00"),
            "stock": 30,
            "image_url": "https://shop.ro/img/phone.jpg",
        }
        feed_item = product_to_feed_item(full_product, item_data, config)
        errors = validate_feed_item(feed_item)
        hard_errors = [e for e in errors if e[2]]
        assert len(hard_errors) == 0

    def test_missing_category(self, config):
        product = Product(
            product_id="NC",
            name="No Cat",
            price=Decimal("10"),
            categories=[],
            photos=[ProductPhoto(url="https://x.jpg", position=0)],
        )
        item_data = {
            "product": product,
            "variant": None,
            "item_id": "NC",
            "sku": None,
            "barcode": None,
            "name": "No Cat",
            "price": Decimal("10"),
            "stock": None,
            "image_url": "https://x.jpg",
        }
        feed_item = product_to_feed_item(product, item_data, config)
        errors = validate_feed_item(feed_item)
        hard_errors = [e for e in errors if e[2]]
        assert any(e[0] == "category" for e in hard_errors)


class TestPriceFormatting:
    def test_plain_price(self):
        assert format_price_plain(Decimal("150.00")) == "150.00"
        assert format_price_plain(Decimal("9.9")) == "9.90"
        assert format_price_plain(None) == ""
