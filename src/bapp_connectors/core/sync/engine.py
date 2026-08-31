"""
Product sync engine — pure Python, no Django dependencies.

Orchestrates bidirectional product and category sync between a ShopPort
adapter and a consumer-provided persistence layer via callbacks.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from bapp_connectors.core.capabilities.bulk_operations import BulkUpsertCapability
from bapp_connectors.core.capabilities.product_management import (
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
)
from bapp_connectors.core.dto import Product, ProductCategory, ProductUpdate
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.sync.dto import CategoryMapping, CategorySyncResult, SyncError, SyncResult

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
        *,
        batch_size: int = 20,
        pause_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> SyncResult:
        """Push products to the provider (create or update).

        Uses BulkUpsertCapability when the adapter has it (batched, with a pause
        between consecutive batches to spare the remote server); otherwise falls
        back to the sequential per-product path.

        Args:
            adapter: A connected ShopPort adapter.
            products: Products to push (framework DTOs with net prices).
            match_fn: Called for each product — returns remote product_id if
                      it already exists on the provider, None if new.
            batch_size: Items per bulk call, capped by adapter.max_batch_size.
            pause_seconds: Slept between consecutive batches (never before the first).
            sleep: Injectable sleep for tests.

        Returns:
            SyncResult with created/updated/skipped/failed counts, remote_ids and remote_meta.
        """
        if isinstance(adapter, BulkUpsertCapability):
            return self._push_products_bulk(adapter, products, match_fn, batch_size, pause_seconds, sleep)
        return self._push_products_sequential(adapter, products, match_fn)

    def _push_products_sequential(self, adapter, products, match_fn) -> SyncResult:
        result = SyncResult()
        can_create = isinstance(adapter, ProductCreationCapability)
        can_full_update = isinstance(adapter, ProductFullUpdateCapability)
        for product in products:
            try:
                remote_id = match_fn(product) if match_fn else None
                if remote_id:
                    # Product exists on provider → update
                    if can_full_update:
                        adapter.update_product(self._product_to_update(product, remote_id))
                    else:
                        # Fall back to stock/price only
                        if product.stock is not None:
                            adapter.update_product_stock(remote_id, product.stock)
                        if product.price is not None:
                            adapter.update_product_price(remote_id, product.price, product.currency)
                    result.updated += 1
                    result.remote_ids[product.product_id] = remote_id
                elif can_create:
                    created = adapter.create_product(product)
                    result.created += 1
                    if created is not None and created.product_id:
                        result.remote_ids[product.product_id] = created.product_id
                else:
                    result.skipped += 1
            except Exception as e:
                result.failed += 1
                result.errors.append(SyncError(
                    product_id=product.product_id,
                    error=str(e),
                    retryable=getattr(e, "retryable", False),
                ))
        return result

    def _push_products_bulk(self, adapter, products, match_fn, batch_size, pause_seconds, sleep) -> SyncResult:
        result = SyncResult()
        size = max(1, min(int(batch_size), int(getattr(adapter, "max_batch_size", 100) or 100)))
        first = True
        for start in range(0, len(products), size):
            chunk = products[start:start + size]
            creates: list[Product] = []
            updates: list[ProductUpdate] = []
            update_src: list[Product] = []
            for product in chunk:
                remote_id = match_fn(product) if match_fn else None
                if remote_id:
                    updates.append(self._product_to_update(product, remote_id))
                    update_src.append(product)
                else:
                    creates.append(product)
            if not creates and not updates:
                continue
            if not first and pause_seconds:
                sleep(pause_seconds)
            first = False
            try:
                bulk = adapter.bulk_upsert_products(creates, updates)
            except Exception as e:
                for product in creates + update_src:
                    result.failed += 1
                    result.errors.append(SyncError(
                        product_id=product.product_id, error=str(e), retryable=getattr(e, "retryable", False),
                    ))
                continue
            self._absorb_bulk(bulk.created, creates, result, created=True)
            self._absorb_bulk(bulk.updated, update_src, result, created=False, remote_ids=[u.product_id for u in updates])
        return result

    @staticmethod
    def _absorb_bulk(items, sources, result: SyncResult, *, created: bool, remote_ids: list[str] | None = None) -> None:
        by_index = {item.index: item for item in items}
        for idx, source in enumerate(sources):
            item = by_index.get(idx)
            if item is None or item.error:
                result.failed += 1
                result.errors.append(SyncError(
                    product_id=source.product_id,
                    error=item.error if item else "no result returned for item",
                    code=item.error_code if item else "",
                    extra=dict(item.extra) if item else {},
                ))
                continue
            if created:
                result.created += 1
            else:
                result.updated += 1
            remote_id = item.remote_id or (remote_ids[idx] if remote_ids else "")
            if remote_id:
                result.remote_ids[source.product_id] = remote_id
            if item.extra:
                result.remote_meta[source.product_id] = dict(item.extra)

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

    def sync_categories(
        self,
        adapter: ShopPort,
        categories: list[ProductCategory],
        existing_mappings: dict[str, str] | None = None,
        *,
        update_existing: bool = False,
        remote_categories: dict[str, ProductCategory] | None = None,
    ) -> CategorySyncResult:
        """Create missing categories (topological order required) and, when
        `update_existing` is set, rename/re-parent mapped ones whose remote snapshot
        (`remote_categories[remote_id]`) differs. Without a snapshot the update is sent
        unconditionally for mapped categories.
        """
        if not isinstance(adapter, CategoryManagementCapability):
            raise TypeError(
                f"Adapter {type(adapter).__name__} does not support CategoryManagementCapability"
            )
        existing = dict(existing_mappings) if existing_mappings else {}
        result = CategorySyncResult()
        for category in categories:
            remote_parent_id = existing.get(category.parent_id) if category.parent_id else None
            if category.category_id in existing:
                if not update_existing:
                    continue
                remote_id = existing[category.category_id]
                snapshot = (remote_categories or {}).get(remote_id)
                if snapshot is not None and snapshot.name == category.name and (snapshot.parent_id or None) == (remote_parent_id or None):
                    continue
                adapter.update_category(ProductCategory(category_id=remote_id, name=category.name, parent_id=remote_parent_id))
                result.updated.append(category.category_id)
                continue
            created = adapter.create_category(name=category.name, parent_id=remote_parent_id)
            result.created.append(CategoryMapping(local_id=category.category_id, remote_id=created.category_id, name=category.name))
            existing[category.category_id] = created.category_id
        return result

    def push_categories(
        self,
        adapter: ShopPort,
        categories: list[ProductCategory],
        existing_mappings: dict[str, str] | None = None,
    ) -> list[CategoryMapping]:
        """Backward-compatible wrapper: create-only, returns the new mappings."""
        return self.sync_categories(adapter, categories, existing_mappings).created

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
            category_ids=product.category_ids if product.category_ids else None,
            photos=product.photos if product.photos else None,
            extra=product.extra,
        )
