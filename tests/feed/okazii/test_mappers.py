"""
Okazii.ro mapper unit tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto.product import (
    Product,
    ProductAttribute,
    ProductPhoto,
    ProductVariant,
)
from bapp_connectors.providers.feed.okazii.mappers import (
    _bool_to_int,
    product_to_feed_item,
    validate_feed_item,
)


@pytest.fixture
def config():
    return {
        "currency": "RON",
        "default_condition": "1",
        "brand_fallback": "DefaultBrand",
        "invoice": "1",
        "warranty": "1",
        "payment_personal": "false",
        "payment_ramburs": "true",
        "payment_avans": "true",
        "delivery_time": "5",
        "courier_name": "Sameday",
        "courier_price": "12.50",
        "return_accept": "true",
        "return_days": "30",
        "include_variants": "true",
    }


@pytest.fixture
def full_product():
    return Product(
        product_id="OK-001",
        sku="OKSKU-001",
        barcode="9999999999999",
        name="Okazii Test Product",
        description="<p>Product with <b>HTML</b> description.</p>",
        price=Decimal("150.00"),
        currency="RON",
        stock=20,
        active=True,
        categories=["Electronics", "Gadgets"],
        photos=[
            ProductPhoto(url="https://shop.ro/img/gadget1.jpg", position=0),
            ProductPhoto(url="https://shop.ro/img/gadget2.jpg", position=1),
        ],
        attributes=[
            ProductAttribute(attribute_id="1", attribute_name="Brand", values=["TechCo"]),
            ProductAttribute(attribute_id="2", attribute_name="Material", values=["Plastic"]),
        ],
    )


class TestProductToFeedItem:
    def test_basic_mapping(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert item.unique_id == "OK-001"
        assert item.title == "Okazii Test Product"
        assert item.price == "150.00"
        assert item.currency == "RON"
        assert item.amount == 20
        assert item.sku == "OKSKU-001"
        assert item.gtin == "9999999999999"
        assert item.brand == "TechCo"
        assert item.in_stock == 1

    def test_html_stripped_from_description(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert "<p>" not in item.description
        assert "<b>" not in item.description
        assert "HTML" in item.description

    def test_category_hierarchy(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert item.category == "Electronics > Gadgets"

    def test_photos_list(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert len(item.photos) == 2
        assert item.photos[0] == "https://shop.ro/img/gadget1.jpg"

    def test_payment_settings(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert item.payment_personal == 0
        assert item.payment_ramburs == 1
        assert item.payment_avans == 1

    def test_delivery_settings(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert item.delivery_time == 5
        assert len(item.couriers) == 1
        assert item.couriers[0].name == "Sameday"
        assert item.couriers[0].price == "12.50"

    def test_return_settings(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert item.return_accept == 1
        assert item.return_days == 30

    def test_condition_and_invoice(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        assert item.state == 1
        assert item.invoice == 1
        assert item.warranty == 1

    def test_non_variant_attributes(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        # Both Brand and Material are not used_for_variants
        assert "Material" in item.attributes
        assert item.attributes["Material"] == "Plastic"

    def test_brand_fallback(self, config):
        product = Product(
            product_id="NB", name="No Brand", price=Decimal("10"),
            stock=1, active=True, categories=["Test"],
            photos=[ProductPhoto(url="https://x.jpg", position=0)],
        )
        item = product_to_feed_item(product, config)
        assert item.brand == "DefaultBrand"

    def test_variant_stocks(self, config):
        product = Product(
            product_id="VS-001",
            name="Variant Stock Product",
            price=Decimal("80"),
            stock=99,
            active=True,
            categories=["Clothing"],
            photos=[ProductPhoto(url="https://x.jpg", position=0)],
            variants=[
                ProductVariant(
                    variant_id="A", stock=4, active=True,
                    attributes={"Size": "S", "Color": "Red"},
                ),
                ProductVariant(
                    variant_id="B", stock=6, active=True,
                    attributes={"Marime": "M", "Culoare": "Blue"},
                    barcode="1111111111111",
                ),
            ],
        )
        item = product_to_feed_item(product, config)
        assert len(item.stocks) == 2
        assert item.amount == 10  # 4 + 6
        assert item.stocks[0].size == "S"
        assert item.stocks[0].color == "Red"
        assert item.stocks[1].size == "M"
        assert item.stocks[1].color == "Blue"
        assert item.stocks[1].gtin == "1111111111111"

    def test_out_of_stock_flag(self, config):
        product = Product(
            product_id="OOS", name="Out of Stock", price=Decimal("10"),
            stock=0, active=True, categories=["Test"],
            photos=[ProductPhoto(url="https://x.jpg", position=0)],
        )
        item = product_to_feed_item(product, config)
        assert item.in_stock == 0

    def test_inactive_product_flag(self, config):
        product = Product(
            product_id="IA", name="Inactive", price=Decimal("10"),
            stock=5, active=False, categories=["Test"],
            photos=[ProductPhoto(url="https://x.jpg", position=0)],
        )
        item = product_to_feed_item(product, config)
        assert item.in_stock == 0

    def test_discount_price(self, full_product, config):
        product = full_product.model_copy(update={"extra": {"sale_price": Decimal("120.00")}})
        item = product_to_feed_item(product, config)
        assert item.discount_price == "120.00"

    def test_no_courier_when_not_configured(self, full_product):
        config = {"currency": "RON", "default_condition": "1"}
        item = product_to_feed_item(full_product, config)
        assert len(item.couriers) == 0


class TestValidateFeedItem:
    def test_valid_item(self, full_product, config):
        item = product_to_feed_item(full_product, config)
        errors = validate_feed_item(item)
        hard_errors = [e for e in errors if e[2]]
        assert len(hard_errors) == 0

    def test_missing_title(self, config):
        product = Product(
            product_id="MT", name="", price=Decimal("10"),
            categories=["Test"],
            photos=[ProductPhoto(url="https://x.jpg", position=0)],
        )
        item = product_to_feed_item(product, config)
        errors = validate_feed_item(item)
        hard_errors = [e for e in errors if e[2]]
        assert any(e[0] == "title" for e in hard_errors)

    def test_missing_photos(self, config):
        product = Product(
            product_id="NP", name="No Photo", price=Decimal("10"),
            categories=["Test"], photos=[],
        )
        item = product_to_feed_item(product, config)
        errors = validate_feed_item(item)
        hard_errors = [e for e in errors if e[2]]
        assert any(e[0] == "photos" for e in hard_errors)

    def test_missing_category(self, config):
        product = Product(
            product_id="NC", name="No Cat", price=Decimal("10"),
            categories=[],
            photos=[ProductPhoto(url="https://x.jpg", position=0)],
        )
        item = product_to_feed_item(product, config)
        errors = validate_feed_item(item)
        hard_errors = [e for e in errors if e[2]]
        assert any(e[0] == "category" for e in hard_errors)


class TestBoolToInt:
    def test_true_values(self):
        assert _bool_to_int("true") == 1
        assert _bool_to_int("1") == 1
        assert _bool_to_int("yes") == 1
        assert _bool_to_int(True) == 1

    def test_false_values(self):
        assert _bool_to_int("false") == 0
        assert _bool_to_int("0") == 0
        assert _bool_to_int("no") == 0
        assert _bool_to_int(False) == 0
