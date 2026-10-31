"""
Social destinations capability — optional interface for connections that reach
several publish targets (e.g. one Meta login -> Facebook pages + Instagram accounts).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto.social import SocialDestination


class SocialDestinationsCapability(ABC):
    """Adapter can list the publish targets available to the connected account."""

    @abstractmethod
    def list_destinations(self) -> list[SocialDestination]:
        """Return every destination the connection can publish to, with its scoped credentials."""
        ...
