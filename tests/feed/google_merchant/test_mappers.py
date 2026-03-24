"""
Google Merchant mapper unit tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto.product import Product, ProductAttribute, ProductPhoto
from bapp_connectors.providers.feed._utils import (
    extract_brand,
    format_price,
    resolve_availability,
    strip_html,
)
from bapp_connectors.providers.feed.google_merchant.mappers import (
    product_to_feed_item,
    resolve_google_category,
    validate_feed_item,
)


@pytest.fixture
def config():
    return {
        "base_url": "https://shop.ro",
        "product_url_template": "{base_url}/p/{product_id}",
        "currency": "RON",
        "default_condition": "new",
        "default_availability": "in stock",
        "brand_fallback": "GenericBrand",
    }


@pytest.fixture
def full_product():
    return Product(
        product_id="P1",
        sku="SKU1",
        barcode="1234567890123",
        name="Test Product",
        description="<b>Bold</b> description with <em>HTML</em>.",
        price=Decimal("100.00"),
        currency="RON",
        stock=10,
        active=True,
        categories=["Cat1", "Cat2"],
        photos=[
            ProductPhoto(url="https://shop.ro/img/main.jpg", position=0),
            ProductPhoto(url="https://shop.ro/img/side.jpg", position=1),
        ],
        attributes=[
            ProductAttribute(attribute_id="1", attribute_name="Brand", values=["TestBrand"]),
        ],
    )


class TestProductToFeedItem:
    def test_basic_mapping(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "P1",
            "sku": "SKU1",
            "barcode": "1234567890123",
            "name": "Test Product",
            "price": Decimal("100.00"),
            "stock": 10,
            "image_url": "https://shop.ro/img/main.jpg",
        }
        result = product_to_feed_item(full_product, item_data, config)
        assert result.id == "P1"
        assert result.title == "Test Product"
        assert result.link == "https://shop.ro/p/P1"
        assert result.price == "100.00 RON"
        assert result.condition == "new"
        assert result.gtin == "1234567890123"
        assert result.mpn == "SKU1"
        assert result.brand == "TestBrand"
        assert result.product_type == "Cat1 > Cat2"

    def test_html_stripped(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "P1",
            "sku": "SKU1",
            "barcode": None,
            "name": "Test",
            "price": Decimal("10"),
            "stock": 1,
            "image_url": "https://shop.ro/img/main.jpg",
        }
        result = product_to_feed_item(full_product, item_data, config)
        assert "<b>" not in result.description
        assert "Bold" in result.description

    def test_brand_fallback(self, config):
        product = Product(product_id="P2", name="No Brand", price=Decimal("50"))
        item_data = {
            "product": product,
            "variant": None,
            "item_id": "P2",
            "sku": None,
            "barcode": None,
            "name": "No Brand",
            "price": Decimal("50"),
            "stock": None,
            "image_url": "",
        }
        result = product_to_feed_item(product, item_data, config)
        assert result.brand == "GenericBrand"


class TestValidateFeedItem:
    def test_valid_item(self, full_product, config):
        item_data = {
            "product": full_product,
            "variant": None,
            "item_id": "P1",
            "sku": "SKU1",
            "barcode": "1234567890123",
            "name": "Test Product",
            "price": Decimal("100.00"),
            "stock": 10,
            "image_url": "https://shop.ro/img/main.jpg",
        }
        feed_item = product_to_feed_item(full_product, item_data, config)
        errors = validate_feed_item(feed_item)
        hard_errors = [e for e in errors if e[2]]
        assert len(hard_errors) == 0

    def test_missing_required_fields(self, config):
        product = Product(product_id="BAD", name="", price=None)
        item_data = {
            "product": product,
            "variant": None,
            "item_id": "BAD",
            "sku": None,
            "barcode": None,
            "name": "",
            "price": None,
            "stock": None,
            "image_url": "",
        }
        feed_item = product_to_feed_item(product, item_data, config)
        errors = validate_feed_item(feed_item)
        hard_errors = [e for e in errors if e[2]]
        assert len(hard_errors) >= 2  # title and image_link at minimum


class TestGoogleProductCategory:
    """Tests for google_product_category resolution."""

    def test_per_product_override(self, config):
        product = Product(
            product_id="GC1", name="Laptop", price=Decimal("3000"),
            categories=["Electronics", "Computers"],
            extra={"google_product_category": "Electronics > Computers > Laptops"},
        )
        result = resolve_google_category(product, config)
        assert result == "Electronics > Computers > Laptops"

    def test_category_mapping_full_path(self, config):
        config["category_mapping"] = '{"Electronics > Computers": "Electronics > Computers > Desktops"}'
        product = Product(
            product_id="GC2", name="Desktop", price=Decimal("2000"),
            categories=["Electronics", "Computers"],
        )
        result = resolve_google_category(product, config)
        assert result == "Electronics > Computers > Desktops"

    def test_category_mapping_single_category(self, config):
        config["category_mapping"] = '{"Electronics": "Electronics"}'
        product = Product(
            product_id="GC3", name="Gadget", price=Decimal("100"),
            categories=["Electronics", "Gadgets"],
        )
        result = resolve_google_category(product, config)
        assert result == "Electronics"

    def test_category_mapping_as_dict(self, config):
        config["category_mapping"] = {"Clothing": "Apparel & Accessories > Clothing"}
        product = Product(
            product_id="GC4", name="Shirt", price=Decimal("50"),
            categories=["Clothing", "T-Shirts"],
        )
        result = resolve_google_category(product, config)
        assert result == "Apparel & Accessories > Clothing"

    def test_default_google_category_fallback(self, config):
        config["default_google_category"] = "General Merchandise"
        product = Product(
            product_id="GC5", name="Widget", price=Decimal("10"),
            categories=["Misc"],
        )
        result = resolve_google_category(product, config)
        assert result == "General Merchandise"

    def test_no_category_returns_empty(self, config):
        product = Product(product_id="GC6", name="Nothing", price=Decimal("5"))
        result = resolve_google_category(product, config)
        assert result == ""

    def test_per_product_overrides_mapping(self, config):
        config["category_mapping"] = '{"Electronics": "Electronics > General"}'
        config["default_google_category"] = "Fallback"
        product = Product(
            product_id="GC7", name="Override", price=Decimal("100"),
            categories=["Electronics"],
            extra={"google_product_category": "Electronics > Specific"},
        )
        result = resolve_google_category(product, config)
        assert result == "Electronics > Specific"  # per-product wins

    def test_mapping_overrides_default(self, config):
        config["category_mapping"] = '{"Electronics": "Electronics > Mapped"}'
        config["default_google_category"] = "Fallback"
        product = Product(
            product_id="GC8", name="Mapped", price=Decimal("100"),
            categories=["Electronics"],
        )
        result = resolve_google_category(product, config)
        assert result == "Electronics > Mapped"  # mapping wins over default

    def test_invalid_json_mapping_falls_through(self, config):
        config["category_mapping"] = "not valid json"
        config["default_google_category"] = "Fallback"
        product = Product(
            product_id="GC9", name="Bad JSON", price=Decimal("10"),
            categories=["Test"],
        )
        result = resolve_google_category(product, config)
        assert result == "Fallback"

    def test_feed_item_includes_google_category(self, config):
        config["default_google_category"] = "Electronics > Audio"
        product = Product(
            product_id="GC10", name="Speaker", price=Decimal("200"),
            categories=["Audio"],
            photos=[ProductPhoto(url="https://shop.ro/speaker.jpg", position=0)],
        )
        item_data = {
            "product": product, "variant": None, "item_id": "GC10",
            "sku": None, "barcode": None, "name": "Speaker",
            "price": Decimal("200"), "stock": 5, "image_url": "https://shop.ro/speaker.jpg",
        }
        feed_item = product_to_feed_item(product, item_data, config)
        assert feed_item.google_product_category == "Electronics > Audio"


class TestUtilities:
    def test_strip_html(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"
        assert strip_html("") == ""
        assert strip_html("plain text") == "plain text"

    def test_format_price(self):
        assert format_price(Decimal("99.99"), "RON") == "99.99 RON"
        assert format_price(Decimal("100"), "EUR") == "100.00 EUR"
        assert format_price(None, "RON") == ""

    def test_resolve_availability_in_stock(self):
        product = Product(product_id="1", stock=10, active=True)
        assert resolve_availability(product) == "in stock"

    def test_resolve_availability_out_of_stock(self):
        product = Product(product_id="1", stock=0, active=True)
        assert resolve_availability(product) == "out of stock"

    def test_resolve_availability_inactive(self):
        product = Product(product_id="1", stock=10, active=False)
        assert resolve_availability(product) == "out of stock"

    def test_extract_brand_from_attribute(self):
        product = Product(
            product_id="1",
            attributes=[ProductAttribute(attribute_id="1", attribute_name="Brand", values=["Sony"])],
        )
        assert extract_brand(product) == "Sony"

    def test_extract_brand_manufacturer(self):
        product = Product(
            product_id="1",
            attributes=[ProductAttribute(attribute_id="1", attribute_name="Manufacturer", values=["Samsung"])],
        )
        assert extract_brand(product) == "Samsung"

    def test_extract_brand_fallback(self):
        product = Product(product_id="1")
        assert extract_brand(product, "FallbackBrand") == "FallbackBrand"
