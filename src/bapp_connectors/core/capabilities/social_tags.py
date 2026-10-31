"""
Social tag search capabilities — optional interfaces for looking up the things
a post can tag: accounts (mentions), catalog products and locations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto.social import SocialLocation, SocialMention, SocialProductTag


class SocialMentionSearchCapability(ABC):
    """Adapter can search accounts that may be mentioned in a post."""

    @abstractmethod
    def search_mentions(self, query: str, limit: int = 10) -> list[SocialMention]:
        """Return accounts matching ``query``."""
        ...


class SocialProductSearchCapability(ABC):
    """Adapter can search catalog products that may be tagged in a post."""

    @abstractmethod
    def search_products(self, query: str, limit: int = 10) -> list[SocialProductTag]:
        """Return taggable products matching ``query``."""
        ...


class SocialLocationSearchCapability(ABC):
    """Adapter can search locations that may be attached to a post."""

    @abstractmethod
    def search_locations(self, query: str, limit: int = 10) -> list[SocialLocation]:
        """Return locations matching ``query``."""
        ...
