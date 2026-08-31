"""
Bulk operation capabilities — optional interfaces for batch updates/imports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import BulkResult, BulkUpsertResult, Product, ProductUpdate


class BulkUpdateCapability(ABC):
    """Adapter supports bulk product updates (stock, price, name)."""

    @abstractmethod
    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        """Update multiple products in a single batch call."""
        ...


class BulkImportCapability(ABC):
    """Adapter supports bulk product import."""

    @abstractmethod
    def bulk_import_products(self, products: list[dict]) -> BulkResult:
        """Import multiple products in a single batch call."""
        ...


class BulkUpsertCapability(ABC):
    """Adapter can create and update products in one provider round-trip.

    Results are positional: ``result.created[i]`` belongs to ``creates[i]``,
    ``result.updated[i]`` to ``updates[i]``. Callers must respect ``max_batch_size``.
    """

    max_batch_size: int = 100

    @abstractmethod
    def bulk_upsert_products(self, creates: list[Product], updates: list[ProductUpdate]) -> BulkUpsertResult:
        """Create `creates` and update `updates` in one batch call."""
        ...
