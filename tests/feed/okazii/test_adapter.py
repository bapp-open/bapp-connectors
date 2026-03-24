"""
Okazii.ro feed adapter tests + contract tests.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from bapp_connectors.core.dto.product import (
    Product,
    ProductAttribute,
    ProductPhoto,
    ProductVariant,
)
from bapp_connectors.providers.feed.okazii.adapter import OkaziiFeedAdapter
from tests.feed.contract import FeedContractTests


@pytest.fixture
def okazii_config(feed_config):
    return {
        **feed_config,
        "default_condition": "1",
        "invoice": "1",
        "warranty": "1",
        "payment_ramburs": "true",
        "payment_avans": "true",
        "payment_personal": "false",
        "delivery_time": "3",
        "courier_name": "Fan Courier",
        "courier_price": "15.99",
        "return_accept": "true",
        "return_days": "14",
    }


@pytest.fixture
def adapter(okazii_config):
    return OkaziiFeedAdapter(credentials={}, config=okazii_config)


class TestOkaziiContract(FeedContractTests):
    """Run all contract tests for Okazii."""

    @pytest.fixture
    def adapter(self, feed_config):
        config = {
            **feed_config,
            "default_condition": "1",
            "courier_name": "Fan Courier",
            "courier_price": "15.99",
        }
        return OkaziiFeedAdapter(credentials={}, config=config)


class TestOkaziiAdapter:
    """Okazii-specific adapter tests."""

    def test_xml_well_formed(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        assert root.tag == "OKAZII"

    def test_xml_contains_auctions(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        auctions = root.findall("AUCTION")
        assert len(auctions) == result.product_count

    def test_auction_core_fields(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("AUCTION")[0]
        assert first.find("UNIQUEID") is not None
        assert first.find("TITLE") is not None
        assert first.find("PRICE") is not None
        assert first.find("CURRENCY") is not None
        assert first.find("AMOUNT") is not None
        assert first.find("CATEGORY") is not None

    def test_photos_section(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for auction in root.findall("AUCTION"):
            uid = auction.find("UNIQUEID").text
            if uid == "PROD-001":
                photos = auction.find("PHOTOS")
                assert photos is not None
                urls = photos.findall("URL")
                assert len(urls) == 3

    def test_payment_section(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("AUCTION")[0]
        payment = first.find("PAYMENT")
        assert payment is not None
        assert payment.find("PERSONAL").text == "0"
        assert payment.find("RAMBURS").text == "1"
        assert payment.find("AVANS").text == "1"

    def test_delivery_section(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("AUCTION")[0]
        delivery = first.find("DELIVERY")
        assert delivery is not None
        assert delivery.find("DELIVERY_TIME").text == "3"
        couriers = delivery.findall("COURIERS")
        assert len(couriers) == 1
        assert couriers[0].find("NAME").text == "Fan Courier"
        assert couriers[0].find("PRICE").text == "15.99"

    def test_return_section(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("AUCTION")[0]
        return_el = first.find("RETURN")
        assert return_el is not None
        assert return_el.find("ACCEPT").text == "1"
        assert return_el.find("DAYS").text == "14"

    def test_attributes_section(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for auction in root.findall("AUCTION"):
            uid = auction.find("UNIQUEID").text
            if uid == "PROD-001":
                attrs = auction.find("ATTRIBUTES")
                assert attrs is not None
                attr_els = attrs.findall("ATTRIBUTE")
                # PROD-001 has Color attribute (not used_for_variants by default)
                names = {a.get("NAME") for a in attr_els}
                assert "Color" in names

    def test_stocks_section_with_variants(self, adapter):
        product = Product(
            product_id="VAR-001",
            name="T-Shirt with Variants",
            description="Test product.",
            price=50,
            currency="RON",
            stock=10,
            active=True,
            categories=["Clothing"],
            photos=[ProductPhoto(url="https://shop.ro/tshirt.jpg", position=0)],
            variants=[
                ProductVariant(
                    variant_id="V1",
                    sku="V1-SKU",
                    name="T-Shirt S Red",
                    stock=3,
                    attributes={"Size": "S", "Color": "Red"},
                ),
                ProductVariant(
                    variant_id="V2",
                    sku="V2-SKU",
                    barcode="1234567890123",
                    name="T-Shirt M Blue",
                    stock=5,
                    attributes={"Size": "M", "Color": "Blue"},
                ),
            ],
        )
        result = adapter.generate_feed([product])
        root = ET.fromstring(result.content)
        auction = root.find("AUCTION")
        stocks = auction.find("STOCKS")
        assert stocks is not None
        stock_els = stocks.findall("STOCK")
        assert len(stock_els) == 2

        # Check first stock
        s1 = stock_els[0]
        assert s1.find("AMOUNT").text == "3"
        assert s1.find("MARIME").text == "S"
        assert s1.find("CULOARE").text == "Red"

        # Check second stock has GTIN
        s2 = stock_els[1]
        assert s2.find("MARIME").text == "M"
        assert s2.find("CULOARE").text == "Blue"
        assert s2.find("GTIN").text == "1234567890123"

    def test_total_amount_from_variants(self, adapter):
        product = Product(
            product_id="VA-001",
            name="Variant Amount Test",
            description="Test.",
            price=30,
            stock=99,  # should be overridden by variant sum
            active=True,
            categories=["Test"],
            photos=[ProductPhoto(url="https://shop.ro/x.jpg", position=0)],
            variants=[
                ProductVariant(variant_id="A", stock=2, attributes={"Size": "S"}),
                ProductVariant(variant_id="B", stock=3, attributes={"Size": "M"}),
            ],
        )
        result = adapter.generate_feed([product])
        root = ET.fromstring(result.content)
        auction = root.find("AUCTION")
        assert auction.find("AMOUNT").text == "5"  # 2 + 3, not 99

    def test_in_stock_flag(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for auction in root.findall("AUCTION"):
            uid = auction.find("UNIQUEID").text
            in_stock = auction.find("IN_STOCK").text
            if uid == "PROD-004":  # stock=0
                assert in_stock == "0"
            elif uid == "PROD-005":  # active=False
                assert in_stock == "0"
            elif uid == "PROD-001":  # stock=50, active=True
                assert in_stock == "1"

    def test_state_condition(self, okazii_config, sample_products):
        okazii_config["default_condition"] = "2"  # used
        adapter = OkaziiFeedAdapter(credentials={}, config=okazii_config)
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("AUCTION")[0]
        assert first.find("STATE").text == "2"

    def test_brand_from_attribute(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for auction in root.findall("AUCTION"):
            uid = auction.find("UNIQUEID").text
            if uid == "PROD-001":
                brand = auction.find("BRAND")
                assert brand is not None
                assert brand.text == "SoundMax"

    def test_sku_and_gtin(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for auction in root.findall("AUCTION"):
            uid = auction.find("UNIQUEID").text
            if uid == "PROD-001":
                assert auction.find("SKU").text == "SKU-001"
                assert auction.find("GTIN").text == "5901234123457"

    def test_description_cdata(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        # PROD-001 has HTML in description — should be stripped and wrapped in CDATA
        assert "CDATA" in result.content

    def test_price_plain_format(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for auction in root.findall("AUCTION"):
            uid = auction.find("UNIQUEID").text
            if uid == "PROD-001":
                assert auction.find("PRICE").text == "299.99"

    def test_supported_formats_xml_only(self, adapter):
        assert adapter.supported_formats() == ["xml"]

    def test_no_courier_when_not_configured(self, sample_products):
        config = {"currency": "RON", "default_condition": "1"}
        adapter = OkaziiFeedAdapter(credentials={}, config=config)
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("AUCTION")[0]
        delivery = first.find("DELIVERY")
        couriers = delivery.findall("COURIERS")
        assert len(couriers) == 0

    def test_discount_price_from_extra(self, adapter):
        product = Product(
            product_id="DP-001",
            name="Discount Product",
            description="Has sale price.",
            price=100,
            stock=5,
            active=True,
            categories=["Test"],
            photos=[ProductPhoto(url="https://shop.ro/dp.jpg", position=0)],
            extra={"sale_price": 79.99},
        )
        result = adapter.generate_feed([product])
        root = ET.fromstring(result.content)
        auction = root.find("AUCTION")
        dp = auction.find("DISCOUNT_PRICE")
        assert dp is not None
        assert dp.text == "79.99"

    def test_skips_product_missing_photos(self, adapter):
        product = Product(
            product_id="NP-001",
            name="No Photo Product",
            description="Has no photos.",
            price=10,
            categories=["Test"],
            photos=[],
        )
        result = adapter.generate_feed([product])
        assert result.skipped_count == 1

    def test_inactive_variants_excluded_from_stocks(self, adapter):
        product = Product(
            product_id="IV-001",
            name="Inactive Variant Test",
            description="Test.",
            price=30,
            stock=10,
            active=True,
            categories=["Test"],
            photos=[ProductPhoto(url="https://shop.ro/iv.jpg", position=0)],
            variants=[
                ProductVariant(variant_id="A", stock=5, active=True, attributes={"Size": "S"}),
                ProductVariant(variant_id="B", stock=3, active=False, attributes={"Size": "M"}),
            ],
        )
        result = adapter.generate_feed([product])
        root = ET.fromstring(result.content)
        stocks = root.find("AUCTION").find("STOCKS")
        assert len(stocks.findall("STOCK")) == 1
        # Total amount should only count active variant
        assert root.find("AUCTION").find("AMOUNT").text == "5"
