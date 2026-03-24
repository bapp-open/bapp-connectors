"""
Facebook Commerce mapper unit tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto.product import Product, ProductAttribute, ProductPhoto
from bapp_connectors.providers.feed.facebook.mappers import (
    product_to_feed_item,
    validate_feed_item,
)


@pytest.fixture
def config():
    return {
        "base_url": "https://shop.ro",
        "product_url_template": "{base_url}/p/{product_id}",
        "currency": "RON",
        "default_condition": "new",
        "brand_fallback": "",
        "apparel_mode": "false",
    }


@pytest.fixture
def full_product():
    return Product(
        product_id="FP1",
        sku="FSKU1",
        barcode="9876543210123",
        name="Facebook Product",
        description="A product for Facebook.",
        price=Decimal("75.50"),
        stock=20,
        active=True,
        categories=["Fashion", "Shoes"],
        photos=[
            ProductPhoto(url="https://shop.ro/img/shoe.jpg", position=0),
            ProductPhoto(url="https://shop.ro/img/shoe2.jpg", position=1),
        ],
        attributes=[
            ProductAttribute(attribute_id="1", attribute_name="Brand", values=["NikeCo"]),
        ],
    )


class TestProductToFeedItem:
    def test_basic_mapping(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "FP1",
            "sku": "FSKU1",
            "barcode": "9876543210123",
            "name": "Facebook Product",
            "price": Decimal("75.50"),
            "stock": 20,
            "image_url": "https://shop.ro/img/shoe.jpg",
        }
        result = product_to_feed_item(full_product, item_data, config)
        assert result.id == "FP1"
        assert result.title == "Facebook Product"
        assert result.price == "75.50 RON"
        assert result.brand == "NikeCo"
        assert result.gtin == "9876543210123"

    def test_apparel_mode_extracts_fields(self, full_product, config):
        config["apparel_mode"] = "true"
        product = Product(
            product_id="AP1",
            name="Apparel Item",
            description="Apparel.",
            price=Decimal("50"),
            stock=5,
            active=True,
            photos=[ProductPhoto(url="https://shop.ro/img/ap.jpg", position=0)],
            attributes=[
                ProductAttribute(attribute_id="1", attribute_name="Gender", values=["Male"]),
                ProductAttribute(attribute_id="2", attribute_name="Color", values=["Blue"]),
                ProductAttribute(attribute_id="3", attribute_name="Size", values=["XL"]),
            ],
        )
        item_data = {
            "product": product,
            "variant": None,
            "item_id": "AP1",
            "sku": None,
            "barcode": None,
            "name": "Apparel Item",
            "price": Decimal("50"),
            "stock": 5,
            "image_url": "https://shop.ro/img/ap.jpg",
        }
        result = product_to_feed_item(product, item_data, config)
        assert result.gender == "Male"
        assert result.color == "Blue"
        assert result.size == "XL"

    def test_additional_images_joined(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "FP1",
            "sku": "FSKU1",
            "barcode": None,
            "name": "Facebook Product",
            "price": Decimal("75.50"),
            "stock": 20,
            "image_url": "https://shop.ro/img/shoe.jpg",
        }
        result = product_to_feed_item(full_product, item_data, config)
        assert "shoe2.jpg" in result.additional_image_link


class TestValidateFeedItem:
    def test_valid_item(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "FP1",
            "sku": "FSKU1",
            "barcode": "9876543210123",
            "name": "Facebook Product",
            "price": Decimal("75.50"),
            "stock": 20,
            "image_url": "https://shop.ro/img/shoe.jpg",
        }
        feed_item = product_to_feed_item(full_product, item_data, config)
        errors = validate_feed_item(feed_item)
        hard_errors = [e for e in errors if e[2]]
        assert len(hard_errors) == 0

    def test_description_required(self, config):
        product = Product(
            product_id="ND", name="No Desc", description="", price=Decimal("10"),
            photos=[ProductPhoto(url="https://shop.ro/x.jpg", position=0)],
        )
        item_data = {
            "product": product,
            "variant": None,
            "item_id": "ND",
            "sku": None,
            "barcode": None,
            "name": "No Desc",
            "price": Decimal("10"),
            "stock": None,
            "image_url": "https://shop.ro/x.jpg",
        }
        feed_item = product_to_feed_item(product, item_data, config)
        errors = validate_feed_item(feed_item)
        hard_errors = [e for e in errors if e[2]]
        assert any(e[0] == "description" for e in hard_errors)
