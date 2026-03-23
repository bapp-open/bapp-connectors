"""
Base port interface that all provider adapters must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ConnectionTestResult
    from bapp_connectors.core.manifest import ProviderManifest


class BasePort(ABC):
    """
    Every adapter must implement this base port.

    Provides credential validation, connection testing, and capability discovery.
    """

    manifest: ProviderManifest

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Validate that the stored credentials are well-formed (not necessarily that they work)."""
        ...

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult:
        """Make a lightweight API call to verify the connection is working."""
        ...

    def supports(self, capability: type) -> bool:
        """Check if this adapter implements a given capability interface."""
        return isinstance(self, capability)
