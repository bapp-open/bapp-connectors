"""
Product feed capability — optional interface for generating product feeds.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class FeedFormat(StrEnum):
    XML = "xml"
    JSON = "json"
    CSV = "csv"


class ProductFeedCapability(ABC):
    """Adapter supports generating product feeds (Google Merchant, Facebook, etc.)."""

    @abstractmethod
    def generate_feed(self, products: list[dict], format: FeedFormat = FeedFormat.XML) -> str | bytes:
        """Generate a product feed in the specified format."""
        ...
