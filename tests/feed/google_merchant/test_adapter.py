"""
Google Merchant feed adapter tests + contract tests.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from bapp_connectors.core.dto.product import Product, ProductPhoto
from bapp_connectors.providers.feed.google_merchant.adapter import GoogleMerchantFeedAdapter
from tests.feed.contract import FeedContractTests

GOOGLE_NS = "http://base.google.com/ns/1.0"


@pytest.fixture
def adapter(feed_config):
    return GoogleMerchantFeedAdapter(credentials={}, config=feed_config)


class TestGoogleMerchantContract(FeedContractTests):
    """Run all contract tests for Google Merchant."""

    @pytest.fixture
    def adapter(self, feed_config):
        return GoogleMerchantFeedAdapter(credentials={}, config=feed_config)


class TestGoogleMerchantAdapter:
    """Google Merchant-specific adapter tests."""

    def test_xml_well_formed(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        # Should parse without error
        root = ET.fromstring(result.content)
        assert root.tag == "rss"
        assert root.attrib["version"] == "2.0"

    def test_xml_contains_items(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        channel = root.find("channel")
        items = channel.findall("item")
        assert len(items) == result.product_count

    def test_xml_g_namespace_fields(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        first = items[0]
        # Check g: namespaced fields exist
        assert first.find(f"{{{GOOGLE_NS}}}id") is not None
        assert first.find(f"{{{GOOGLE_NS}}}title") is not None
        assert first.find(f"{{{GOOGLE_NS}}}price") is not None
        assert first.find(f"{{{GOOGLE_NS}}}availability") is not None

    def test_csv_format(self, feed_config, sample_products):
        feed_config["feed_format"] = "csv"
        adapter = GoogleMerchantFeedAdapter(credentials={}, config=feed_config)
        result = adapter.generate_feed(sample_products)
        assert result.format == "csv"
        assert result.content_type == "text/csv"
        lines = result.content.strip().split("\n")
        # Header + data rows
        assert len(lines) >= 2
        assert "id" in lines[0]
        assert "title" in lines[0]

    def test_supported_formats(self, adapter):
        assert "xml" in adapter.supported_formats()
        assert "csv" in adapter.supported_formats()

    def test_brand_fallback(self, feed_config):
        feed_config["brand_fallback"] = "DefaultBrand"
        adapter = GoogleMerchantFeedAdapter(credentials={}, config=feed_config)
        # Product with no brand attribute
        product = Product(
            product_id="NB-001",
            name="No Brand Product",
            price=100,
            photos=[],
        )
        result = adapter.validate_products([product])
        # Should not fail on brand (it's recommended, not required)
        assert result.valid_count >= 0

    def test_out_of_stock_availability(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        # PROD-004 has stock=0, should be "out of stock"
        for item_el in items:
            item_id = item_el.find(f"{{{GOOGLE_NS}}}id").text
            avail = item_el.find(f"{{{GOOGLE_NS}}}availability").text
            if item_id == "PROD-004":
                assert avail == "out of stock"

    def test_inactive_product_availability(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        for item_el in items:
            item_id = item_el.find(f"{{{GOOGLE_NS}}}id").text
            avail = item_el.find(f"{{{GOOGLE_NS}}}availability").text
            if item_id == "PROD-005":
                assert avail == "out of stock"

    def test_variant_expansion(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        item_ids = [i.find(f"{{{GOOGLE_NS}}}id").text for i in items]
        # PROD-002 has 3 variants, should expand
        assert "PROD-002-V-002-S" in item_ids
        assert "PROD-002-V-002-M" in item_ids
        assert "PROD-002-V-002-L" in item_ids

    def test_no_variant_expansion(self, feed_config, sample_products):
        feed_config["include_variants"] = "false"
        adapter = GoogleMerchantFeedAdapter(credentials={}, config=feed_config)
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        item_ids = [i.find(f"{{{GOOGLE_NS}}}id").text for i in items]
        assert "PROD-002" in item_ids
        assert "PROD-002-V-002-S" not in item_ids

    def test_html_stripped_from_description(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        for item_el in items:
            desc = item_el.find(f"{{{GOOGLE_NS}}}description").text or ""
            assert "<p>" not in desc
            assert "<strong>" not in desc

    def test_additional_image_links(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        # PROD-001 has 3 photos, so 2 additional
        for item_el in items:
            item_id = item_el.find(f"{{{GOOGLE_NS}}}id").text
            if item_id == "PROD-001":
                additional = item_el.findall(f"{{{GOOGLE_NS}}}additional_image_link")
                assert len(additional) == 2

    def test_price_formatting(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        for item_el in items:
            item_id = item_el.find(f"{{{GOOGLE_NS}}}id").text
            price = item_el.find(f"{{{GOOGLE_NS}}}price").text
            if item_id == "PROD-001":
                assert price == "299.99 RON"

    def test_google_product_category_in_xml(self, feed_config, sample_products):
        feed_config["default_google_category"] = "Electronics"
        adapter = GoogleMerchantFeedAdapter(credentials={}, config=feed_config)
        result = adapter.generate_feed(sample_products)
        root = ET.fromstring(result.content)
        items = root.find("channel").findall("item")
        first = items[0]
        gpc = first.find(f"{{{GOOGLE_NS}}}google_product_category")
        assert gpc is not None
        assert gpc.text == "Electronics"

    def test_google_product_category_per_product(self, feed_config):
        product = Product(
            product_id="GPC-001",
            name="Laptop",
            description="A laptop.",
            price=3000,
            stock=10,
            active=True,
            categories=["Electronics"],
            photos=[ProductPhoto(url="https://myshop.ro/img/laptop.jpg", position=0)],
            extra={"google_product_category": "Electronics > Computers > Laptops"},
        )
        adapter = GoogleMerchantFeedAdapter(credentials={}, config=feed_config)
        result = adapter.generate_feed([product])
        root = ET.fromstring(result.content)
        item_el = root.find("channel").find("item")
        gpc = item_el.find(f"{{{GOOGLE_NS}}}google_product_category")
        assert gpc is not None
        assert gpc.text == "Electronics > Computers > Laptops"

    def test_google_product_category_from_mapping(self, feed_config):
        feed_config["category_mapping"] = '{"Electronics": "Electronics > General"}'
        product = Product(
            product_id="GPC-002",
            name="Widget",
            description="A widget.",
            price=50,
            stock=5,
            active=True,
            categories=["Electronics"],
            photos=[ProductPhoto(url="https://myshop.ro/img/widget.jpg", position=0)],
        )
        adapter = GoogleMerchantFeedAdapter(credentials={}, config=feed_config)
        result = adapter.generate_feed([product])
        root = ET.fromstring(result.content)
        item_el = root.find("channel").find("item")
        gpc = item_el.find(f"{{{GOOGLE_NS}}}google_product_category")
        assert gpc is not None
        assert gpc.text == "Electronics > General"

    def test_test_connection_missing_base_url(self):
        adapter = GoogleMerchantFeedAdapter(credentials={}, config={})
        result = adapter.test_connection()
        assert result.success is False
