"""Product lookup capability — find a remote product by its SKU."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Product


class ProductLookupCapability(ABC):
    """Adapter can resolve a remote product by SKU (used to adopt pre-existing products)."""

    @abstractmethod
    def find_product_by_sku(self, sku: str) -> Product | None:
        """Return the remote product with this exact SKU, or None."""
        ...
