"""
Bulk operation capabilities — optional interfaces for batch updates/imports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import BulkResult, ProductUpdate


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
