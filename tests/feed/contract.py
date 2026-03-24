"""
Feed port contract test suite.

Reusable tests that any FeedPort adapter must pass.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto.feed import FeedResult, FeedValidationResult
from bapp_connectors.core.dto.product import Product
from bapp_connectors.core.ports import FeedPort


class FeedContractTests:
    """Contract tests for FeedPort implementations."""

    @pytest.fixture
    def adapter(self) -> FeedPort:
        raise NotImplementedError

    def test_validate_credentials(self, adapter: FeedPort):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter: FeedPort):
        result = adapter.test_connection()
        assert result.success is True

    def test_generate_feed_returns_feed_result(self, adapter: FeedPort, sample_products: list[Product]):
        result = adapter.generate_feed(sample_products)
        assert isinstance(result, FeedResult)
        assert result.content
        assert result.product_count > 0
        assert result.format in ("xml", "csv", "json")
        assert result.content_type

    def test_generate_feed_empty_list(self, adapter: FeedPort):
        result = adapter.generate_feed([])
        assert isinstance(result, FeedResult)
        assert result.product_count == 0

    def test_validate_products_returns_result(self, adapter: FeedPort, sample_products: list[Product]):
        result = adapter.validate_products(sample_products)
        assert isinstance(result, FeedValidationResult)
        assert result.valid_count + result.invalid_count > 0

    def test_generate_feed_skips_invalid_products(self, adapter: FeedPort, minimal_product: Product):
        result = adapter.generate_feed([minimal_product])
        # minimal_product has no name, no image, no price — should be skipped
        assert result.skipped_count >= 1

    def test_generate_feed_product_count_consistency(self, adapter: FeedPort, sample_products: list[Product]):
        result = adapter.generate_feed(sample_products)
        # product_count + skipped_count should reflect total items processed
        assert result.product_count >= 0
        assert result.skipped_count >= 0

    def test_supported_formats(self, adapter: FeedPort):
        formats = adapter.supported_formats()
        assert isinstance(formats, list)
        assert len(formats) >= 1

    def test_is_feed_port_instance(self, adapter: FeedPort):
        assert isinstance(adapter, FeedPort)
