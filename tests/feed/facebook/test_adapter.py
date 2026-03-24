"""
Facebook Commerce feed adapter tests + contract tests.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET

import pytest

from bapp_connectors.core.dto.product import Product, ProductAttribute, ProductPhoto, ProductVariant
from bapp_connectors.providers.feed.facebook.adapter import FacebookFeedAdapter
from tests.feed.contract import FeedContractTests


@pytest.fixture
def adapter(feed_config):
    return FacebookFeedAdapter(credentials={}, config=feed_config)


class TestFacebookContract(FeedContractTests):
    """Run all contract tests for Facebook."""

    @pytest.fixture
    def adapter(self, feed_config):
        return FacebookFeedAdapter(credentials={}, config=feed_config)


class TestFacebookAdapter:
    """Facebook-specific adapter tests."""

    def test_csv_default_format(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        assert result.format == "csv"
        assert result.content_type == "text/csv"

    def test_csv_parseable(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        reader = csv.reader(io.StringIO(result.content))
        rows = list(reader)
        assert len(rows) >= 2  # header + at least 1 data row
        header = rows[0]
        assert "id" in header
        assert "title" in header
        assert "price" in header

    def test_xml_format(self, feed_config, sample_products):
        feed_config["feed_format"] = "xml"
        adapter = FacebookFeedAdapter(credentials={}, config=feed_config)
        result = adapter.generate_feed(sample_products)
        assert result.format == "xml"
        assert result.content_type == "application/xml"
        root = ET.fromstring(result.content)
        assert root.tag == "rss"

    def test_apparel_mode_csv_columns(self, feed_config, sample_products):
        feed_config["apparel_mode"] = "true"
        adapter = FacebookFeedAdapter(credentials={}, config=feed_config)
        result = adapter.generate_feed(sample_products)
        reader = csv.reader(io.StringIO(result.content))
        header = next(reader)
        assert "gender" in header
        assert "age_group" in header
        assert "color" in header
        assert "size" in header

    def test_apparel_values_from_attributes(self, feed_config):
        feed_config["apparel_mode"] = "true"
        adapter = FacebookFeedAdapter(credentials={}, config=feed_config)
        product = Product(
            product_id="AP-001",
            name="Summer Dress",
            description="Light summer dress.",
            price=100,
            stock=10,
            active=True,
            photos=[ProductPhoto(url="https://shop.ro/dress.jpg", position=0)],
            attributes=[
                ProductAttribute(attribute_id="1", attribute_name="Gender", values=["Female"]),
                ProductAttribute(attribute_id="2", attribute_name="Color", values=["Red"]),
                ProductAttribute(attribute_id="3", attribute_name="Brand", values=["FashionCo"]),
            ],
        )
        result = adapter.generate_feed([product])
        reader = csv.reader(io.StringIO(result.content))
        header = next(reader)
        data = next(reader)
        gender_idx = header.index("gender")
        color_idx = header.index("color")
        assert data[gender_idx] == "Female"
        assert data[color_idx] == "Red"

    def test_variant_expansion_csv(self, adapter, sample_products):
        result = adapter.generate_feed(sample_products)
        reader = csv.reader(io.StringIO(result.content))
        header = next(reader)
        id_idx = header.index("id")
        ids = [row[id_idx] for row in reader]
        # PROD-002 has 3 variants
        assert "PROD-002-V-002-S" in ids
        assert "PROD-002-V-002-M" in ids

    def test_supported_formats(self, adapter):
        assert set(adapter.supported_formats()) == {"csv", "xml"}

    def test_test_connection_missing_base_url(self):
        adapter = FacebookFeedAdapter(credentials={}, config={})
        result = adapter.test_connection()
        assert result.success is False

    def test_description_required(self, feed_config):
        adapter = FacebookFeedAdapter(credentials={}, config=feed_config)
        product = Product(
            product_id="ND-001",
            name="No Description",
            description="",
            price=10,
            photos=[ProductPhoto(url="https://shop.ro/nd.jpg", position=0)],
        )
        result = adapter.generate_feed([product])
        # Description is required for Facebook — should be skipped
        assert result.skipped_count == 1
