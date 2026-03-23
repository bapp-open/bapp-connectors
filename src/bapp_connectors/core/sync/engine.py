"""
Product sync engine — pure Python, no Django dependencies.

Orchestrates bidirectional product and category sync between a ShopPort
adapter and a consumer-provided persistence layer via callbacks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from bapp_connectors.core.capabilities.product_management import (
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
)
from bapp_connectors.core.dto import Product, ProductCategory, ProductUpdate
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.sync.dto import CategoryMapping, SyncError, SyncResult

logger = logging.getLogger(__name__)


class ProductMatcher(Protocol):
    """Protocol for checking if a product already exists on the provider."""

    def __call__(self, product: Product) -> str | None:
        """Return remote product_id if it exists, None if it needs creation."""
        ...


class ProductSyncEngine:
    """
    Bidirectional product sync engine. Pure Python, no Django.

    The engine orchestrates sync operations by calling adapter methods
    and consumer-provided callbacks. It never persists anything itself.

    Usage:
        engine = ProductSyncEngine()
        adapter = connection.get_adapter()

        # Pull: provider → local
        result = engine.pull_products(adapter, on_product=save_to_db)

        # Push: local → provider
        result = engine.push_products(adapter, products, match_fn=find_remote_id)
    """

    # ── Pull (provider → local) ──

    def pull_products(
        self,
        adapter: ShopPort,
        on_product: Callable[[Product], None],
        cursor: str | None = None,
    ) -> SyncResult:
        """Pull all products from the provider, calling on_product for each.

        Iterates through all pages. The consumer's on_product callback
        handles persistence (e.g., saving to Django models).

        Args:
            adapter: A connected ShopPort adapter.
            on_product: Called for each product. Raise to signal error.
            cursor: Resume from a previous sync cursor.

        Returns:
            SyncResult with counts.
        """
        result = SyncResult()
        current_cursor = cursor

        while True:
            page = adapter.get_products(cursor=current_cursor)
            for product in page.items:
                try:
                    on_product(product)
                    result.updated += 1
                except Exception as e:
                    result.failed += 1
                    result.errors.append(SyncError(
                        product_id=product.product_id,
                        error=str(e),
                        retryable=getattr(e, "retryable", False),
                    ))

            if not page.has_more:
                break
            current_cursor = page.cursor

        return result

    # ── Push (local → provider) ──

    def push_products(
        self,
        adapter: ShopPort,
        products: list[Product],
        match_fn: ProductMatcher | None = None,
    ) -> SyncResult:
        """Push products to the provider (create or update).

        Args:
            adapter: A connected ShopPort adapter.
            products: Products to push (framework DTOs with net prices).
            match_fn: Called for each product — returns remote product_id if
                      it already exists on the provider, None if new.
                      If None, all products are treated as creates.

        Returns:
            SyncResult with created/updated/skipped/failed counts.
        """
        result = SyncResult()
        can_create = isinstance(adapter, ProductCreationCapability)
        can_full_update = isinstance(adapter, ProductFullUpdateCapability)

        for product in products:
            try:
                remote_id = match_fn(product) if match_fn else None

                if remote_id:
                    # Product exists on provider → update
                    if can_full_update:
                        update = self._product_to_update(product, remote_id)
                        adapter.update_product(update)
                    else:
                        # Fall back to stock/price only
                        if product.stock is not None:
                            adapter.update_product_stock(remote_id, product.stock)
                        if product.price is not None:
                            adapter.update_product_price(remote_id, product.price, product.currency)
                    result.updated += 1
                elif can_create:
                    # New product → create
                    adapter.create_product(product)
                    result.created += 1
                else:
                    # Can't create → skip
                    result.skipped += 1
            except Exception as e:
                result.failed += 1
                result.errors.append(SyncError(
                    product_id=product.product_id,
                    error=str(e),
                    retryable=getattr(e, "retryable", False),
                ))

        return result

    # ── Categories ──

    def pull_categories(self, adapter: ShopPort) -> list[ProductCategory]:
        """Pull categories from the provider.

        Requires adapter to implement CategoryManagementCapability.
        Returns a flat list with parent_id for hierarchy.
        """
        if not isinstance(adapter, CategoryManagementCapability):
            raise TypeError(
                f"Adapter {type(adapter).__name__} does not support CategoryManagementCapability"
            )
        return adapter.get_categories()

    def push_categories(
        self,
        adapter: ShopPort,
        categories: list[ProductCategory],
        existing_mappings: dict[str, str] | None = None,
    ) -> list[CategoryMapping]:
        """Push categories to the provider, returning local→remote mappings.

        Categories MUST be provided in topological order (parents before children).

        Args:
            adapter: Must implement CategoryManagementCapability with create_category.
            categories: Ordered list of categories to push.
            existing_mappings: Dict of {local_category_id: remote_category_id}
                              for already-synced categories. These are skipped.

        Returns:
            List of CategoryMapping for newly created categories.
        """
        if not isinstance(adapter, CategoryManagementCapability):
            raise TypeError(
                f"Adapter {type(adapter).__name__} does not support CategoryManagementCapability"
            )

        existing = dict(existing_mappings) if existing_mappings else {}
        new_mappings: list[CategoryMapping] = []

        for category in categories:
            if category.category_id in existing:
                continue

            # Resolve parent_id to remote parent_id
            remote_parent_id = None
            if category.parent_id:
                remote_parent_id = existing.get(category.parent_id)

            created = adapter.create_category(
                name=category.name,
                parent_id=remote_parent_id,
            )
            mapping = CategoryMapping(
                local_id=category.category_id,
                remote_id=created.category_id,
                name=category.name,
            )
            new_mappings.append(mapping)
            # Track for subsequent parent_id resolution
            existing[category.category_id] = created.category_id

        return new_mappings

    # ── Helpers ──

    @staticmethod
    def _product_to_update(product: Product, remote_id: str) -> ProductUpdate:
        """Convert a Product DTO to a ProductUpdate for an existing remote product."""
        return ProductUpdate(
            product_id=remote_id,
            sku=product.sku,
            barcode=product.barcode,
            name=product.name,
            description=product.description,
            price=product.price,
            currency=product.currency,
            stock=product.stock,
            active=product.active,
            categories=product.categories if product.categories else None,
            photos=product.photos if product.photos else None,
            extra=product.extra,
        )
