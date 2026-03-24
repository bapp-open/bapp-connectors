"""
Tests for feed product filtering (categories_exclude, only_in_stock).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto.product import Product, ProductPhoto, ProductVariant
from bapp_connectors.providers.feed._utils import filter_products


@pytest.fixture
def products():
    return [
        Product(
            product_id="P1", name="Electronics Item", price=Decimal("100"),
            stock=10, active=True, categories=["Electronics", "Gadgets"],
        ),
        Product(
            product_id="P2", name="Clothing Item", price=Decimal("50"),
            stock=5, active=True, categories=["Clothing", "T-Shirts"],
        ),
        Product(
            product_id="P3", name="Out of Stock", price=Decimal("30"),
            stock=0, active=True, categories=["Electronics"],
        ),
        Product(
            product_id="P4", name="Unknown Stock", price=Decimal("20"),
            stock=None, active=True, categories=["Office"],
        ),
        Product(
            product_id="P5", name="Food Item", price=Decimal("10"),
            stock=100, active=True, categories=["Food", "Snacks"],
        ),
    ]


class TestOnlyInStock:
    def test_disabled_by_default(self, products):
        result = filter_products(products, {})
        assert len(result) == 5

    def test_excludes_zero_stock(self, products):
        result = filter_products(products, {"only_in_stock": "true"})
        ids = [p.product_id for p in result]
        assert "P3" not in ids  # stock=0
        assert "P1" in ids  # stock=10
        assert "P4" in ids  # stock=None → unknown, assume in stock

    def test_keeps_unknown_stock(self, products):
        result = filter_products(products, {"only_in_stock": "true"})
        ids = [p.product_id for p in result]
        assert "P4" in ids

    def test_variant_with_stock_kept(self):
        product = Product(
            product_id="VP1", name="Variant Product", price=Decimal("50"),
            stock=0, active=True,
            variants=[
                ProductVariant(variant_id="V1", stock=3, active=True),
            ],
        )
        result = filter_products([product], {"only_in_stock": "true"})
        assert len(result) == 1  # parent stock=0 but variant has stock

    def test_variant_all_out_of_stock(self):
        product = Product(
            product_id="VP2", name="Empty Variants", price=Decimal("50"),
            stock=0, active=True,
            variants=[
                ProductVariant(variant_id="V1", stock=0, active=True),
                ProductVariant(variant_id="V2", stock=0, active=False),
            ],
        )
        result = filter_products([product], {"only_in_stock": "true"})
        assert len(result) == 0


class TestCategoriesExclude:
    def test_no_exclusions(self, products):
        result = filter_products(products, {"categories_exclude": ""})
        assert len(result) == 5

    def test_exclude_single_category(self, products):
        result = filter_products(products, {"categories_exclude": "Food"})
        ids = [p.product_id for p in result]
        assert "P5" not in ids
        assert len(result) == 4

    def test_exclude_multiple_categories(self, products):
        result = filter_products(products, {"categories_exclude": "Food, Clothing"})
        ids = [p.product_id for p in result]
        assert "P2" not in ids  # has Clothing
        assert "P5" not in ids  # has Food
        assert len(result) == 3

    def test_case_insensitive(self, products):
        result = filter_products(products, {"categories_exclude": "electronics"})
        ids = [p.product_id for p in result]
        assert "P1" not in ids  # has Electronics
        assert "P3" not in ids  # has Electronics
        assert len(result) == 3

    def test_json_list_format(self, products):
        result = filter_products(products, {"categories_exclude": '["Food", "Office"]'})
        ids = [p.product_id for p in result]
        assert "P4" not in ids  # Office
        assert "P5" not in ids  # Food
        assert len(result) == 3

    def test_python_list_format(self, products):
        result = filter_products(products, {"categories_exclude": ["Food", "Office"]})
        ids = [p.product_id for p in result]
        assert "P4" not in ids
        assert "P5" not in ids

    def test_excludes_if_any_category_matches(self, products):
        # P1 has ["Electronics", "Gadgets"] — exclude "Gadgets" should remove it
        result = filter_products(products, {"categories_exclude": "Gadgets"})
        ids = [p.product_id for p in result]
        assert "P1" not in ids


class TestCombinedFilters:
    def test_both_filters(self, products):
        result = filter_products(products, {
            "only_in_stock": "true",
            "categories_exclude": "Food",
        })
        ids = [p.product_id for p in result]
        assert "P3" not in ids  # out of stock
        assert "P5" not in ids  # excluded category
        assert "P1" in ids
        assert "P2" in ids
        assert "P4" in ids  # unknown stock, not Food
