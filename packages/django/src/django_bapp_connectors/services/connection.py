"""
Connection service — adapter instantiation, connection testing, credential management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bapp_connectors.core.registry import registry

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ConnectionTestResult
    from bapp_connectors.core.ports import BasePort

logger = logging.getLogger(__name__)


class ConnectionService:
    """Service layer for managing connector connections."""

    @staticmethod
    def get_adapter(connection) -> BasePort:
        """Instantiate the right adapter from a Connection model instance."""
        return registry.create_adapter(
            family=connection.provider_family,
            provider=connection.provider_name,
            credentials=connection.credentials,
        )

    @staticmethod
    def test_connection(connection) -> ConnectionTestResult:
        """Test a connection and update its status."""
        adapter = ConnectionService.get_adapter(connection)
        result = adapter.test_connection()
        connection.is_connected = result.success
        connection.save(update_fields=["is_connected", "updated_at"])
        return result

    @staticmethod
    def rotate_credentials(connection, new_credentials: dict) -> None:
        """Update connection credentials (encrypted)."""
        connection.credentials = new_credentials
        connection.save(update_fields=["credentials_encrypted", "updated_at"])

    @staticmethod
    def list_available_providers(family: str | None = None):
        """List all registered provider manifests."""
        return registry.list_providers(family=family)
