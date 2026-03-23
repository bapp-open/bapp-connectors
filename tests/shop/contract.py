"""
Shop port contract test suite.

Provides a reusable base class that any ShopPort adapter must pass.
Subclass ShopContractTests, implement the `adapter` fixture, and all
contract tests run automatically.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto import Order, PaginatedResult, Product
from bapp_connectors.core.ports import ShopPort


class ShopContractTests:
    """
    Contract tests for ShopPort implementations.

    Verifies: connection, orders, products, stock update, price update.

    Subclasses MUST provide:
    - `adapter` fixture returning a connected ShopPort instance
    - `product_factory` fixture returning a callable that creates a test product
      and returns (product_id, cleanup_fn). Optional — tests that need it will skip if missing.
    """

    @pytest.fixture
    def adapter(self) -> ShopPort:
        """Override in subclass to provide a connected adapter."""
        raise NotImplementedError

    # ── Connection ──

    def test_validate_credentials(self, adapter: ShopPort):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter: ShopPort):
        result = adapter.test_connection()
        assert result.success is True, f"Connection failed: {result.message}"

    # ── Orders ──

    def test_get_orders_returns_paginated_result(self, adapter: ShopPort):
        result = adapter.get_orders()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    def test_get_orders_items_are_order_dtos(self, adapter: ShopPort):
        result = adapter.get_orders()
        for order in result.items:
            assert isinstance(order, Order)
            assert order.order_id

    def test_get_orders_have_provider_meta(self, adapter: ShopPort):
        result = adapter.get_orders()
        for order in result.items:
            assert order.provider_meta is not None
            assert order.provider_meta.provider

    # ── Products ──

    def test_get_products_returns_paginated_result(self, adapter: ShopPort):
        result = adapter.get_products()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    def test_get_products_items_are_product_dtos(self, adapter: ShopPort):
        result = adapter.get_products()
        for product in result.items:
            assert isinstance(product, Product)
            assert product.product_id

    def test_get_products_have_provider_meta(self, adapter: ShopPort):
        result = adapter.get_products()
        for product in result.items:
            assert product.provider_meta is not None
            assert product.provider_meta.provider
