"""
Feed port — contract for product feed generators.

Feed providers transform Product DTOs into platform-specific output
formats (XML, CSV) for Google Merchant, Facebook, Compari.ro, etc.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from .base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto.feed import FeedResult, FeedValidationResult
    from bapp_connectors.core.dto.product import Product


class FeedPort(BasePort):
    """
    Common contract for all product feed generators.

    Feed providers take normalized Product DTOs and produce
    platform-specific output (XML, CSV) with proper field
    mapping, validation, and formatting.
    """

    @abstractmethod
    def generate_feed(self, products: list[Product]) -> FeedResult:
        """Generate a product feed from normalized Product DTOs.

        The adapter applies platform-specific field mapping, validation,
        and formatting rules. Settings like base_url, default_condition,
        and brand_fallback come from the adapter's config.

        Products that fail validation are skipped (not included in output)
        and counted in FeedResult.skipped_count.
        """
        ...

    @abstractmethod
    def validate_products(self, products: list[Product]) -> FeedValidationResult:
        """Validate products against this feed platform's requirements.

        Useful for pre-flight checks without generating the full feed.
        """
        ...

    def supported_formats(self) -> list[str]:
        """Return the feed formats this provider supports."""
        return ["xml"]
