"""
Product feed capabilities — interfaces for feed generation and upload.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto.feed import FeedResult, FeedUploadResult


class FeedFormat(StrEnum):
    XML = "xml"
    JSON = "json"
    CSV = "csv"


class ProductFeedCapability(ABC):
    """Adapter supports generating product feeds (Google Merchant, Facebook, etc.).

    .. deprecated:: Use FeedPort for new feed providers instead.
    """

    @abstractmethod
    def generate_feed(self, products: list[dict], format: FeedFormat = FeedFormat.XML) -> str | bytes:
        """Generate a product feed in the specified format."""
        ...


class FeedUploadCapability(ABC):
    """Feed provider supports uploading the generated feed to the platform API."""

    @abstractmethod
    def upload_feed(self, feed: FeedResult) -> FeedUploadResult:
        """Upload a generated feed to the platform (Google Content API, Facebook Catalog API, etc.)."""
        ...
