"""
Compari.ro feed adapter tests + contract tests.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET

import pytest

from bapp_connectors.core.dto.product import Product, ProductPhoto
from bapp_connectors.providers.feed.compari.adapter import CompariFeedAdapter
from tests.feed.contract import FeedContractTests


@pytest.fixture
def compari_config(feed_config):
    return {
        **feed_config,
        "manufacturer_fallback": "",
        "default_delivery_time": "1-3 zile",
        "default_delivery_cost": "15.99",
    }


@pytest.fixture
def adapter(compari_config):
    return CompariFeedAdapter(credentials={}, config=compari_config)


class TestCompariContract(FeedContractTests):
    """Run all contract tests for Compari.ro."""

    @pytest.fixture
    def adapter(self, feed_config):
        config = {
            **feed_config,
            "manufacturer_fallback": "",
            "default_delivery_time": "1-3 zile",
            "default_delivery_cost": "15.99",
        }
        return CompariFeedAdapter(credentials={}, config=config)


class TestCompariAdapter:
    """Compari.ro-specific adapter tests."""

    def test_xml_well_formed(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        assert root.tag == "products"

    def test_xml_contains_products(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        products_el = root.findall("product")
        assert len(products_el) == result.product_count

    def test_xml_fields(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("product")[0]
        assert first.find("identifier") is not None
        assert first.find("name") is not None
        assert first.find("price") is not None
        assert first.find("product_url") is not None
        assert first.find("currency") is not None

    def test_delivery_info(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        first = root.findall("product")[0]
        delivery_time = first.find("delivery_time")
        delivery_cost = first.find("delivery_cost")
        assert delivery_time is not None
        assert delivery_time.text == "1-3 zile"
        assert delivery_cost is not None
        assert delivery_cost.text == "15.99"

    def test_csv_format(self, compari_config, sample_products):
        compari_config["feed_format"] = "csv"
        adapter = CompariFeedAdapter(credentials={}, config=compari_config)
        result = adapter.generate_feed(sample_products)
        assert result.format == "csv"
        assert result.content_type == "text/csv"
        reader = csv.reader(io.StringIO(result.content))
        header = next(reader)
        assert "identifier" in header
        assert "manufacturer" in header
        assert "currency" in header

    def test_manufacturer_from_attribute(self, compari_config, sample_products):
        adapter = CompariFeedAdapter(credentials={}, config=compari_config)
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        # PROD-001 has Brand=SoundMax attribute
        for product_el in root.findall("product"):
            if product_el.find("identifier").text == "PROD-001":
                manufacturer = product_el.find("manufacturer")
                assert manufacturer is not None
                assert manufacturer.text == "SoundMax"

    def test_category_formatting(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for product_el in root.findall("product"):
            if product_el.find("identifier").text == "PROD-001":
                category = product_el.find("category").text
                assert "Electronics" in category
                assert ">" in category

    def test_variant_expansion(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        ids = [p.find("identifier").text for p in root.findall("product")]
        assert "PROD-002-V-002-S" in ids

    def test_ean_code(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for product_el in root.findall("product"):
            if product_el.find("identifier").text == "PROD-001":
                ean = product_el.find("ean_code")
                assert ean is not None
                assert ean.text == "5901234123457"

    def test_price_plain_format(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        for product_el in root.findall("product"):
            if product_el.find("identifier").text == "PROD-001":
                price = product_el.find("price").text
                assert price == "299.99"  # no currency suffix

    def test_supported_formats(self, adapter):
        assert "xml" in adapter.supported_formats()
        assert "csv" in adapter.supported_formats()

    def test_test_connection_missing_base_url(self):
        adapter = CompariFeedAdapter(credentials={}, config={})
        result = adapter.test_connection()
        assert result.success is False

    def test_skips_product_missing_category(self, compari_config):
        adapter = CompariFeedAdapter(credentials={}, config=compari_config)
        product = Product(
            product_id="NC-001",
            name="No Category",
            description="Has no category.",
            price=50,
            categories=[],
            photos=[ProductPhoto(url="https://shop.ro/nc.jpg", position=0)],
        )
        result = adapter.generate_feed([product])
        # Category is required for Compari.ro
        assert result.skipped_count == 1
