"""
Sync service — incremental and full resync orchestration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    items_fetched: int = 0
    items_processed: int = 0
    cursor: str = ""
    has_more: bool = False
    errors: list[str] = field(default_factory=list)


class SyncService:
    """Service layer for sync operations."""

    @staticmethod
    def incremental_sync(connection, sync_state, resource_type: str, fetch_fn=None) -> SyncResult:
        """
        Resume from cursor, fetch new data, return SyncResult.

        Args:
            connection: The connection model instance.
            sync_state: The SyncState model instance for this resource.
            resource_type: e.g., 'orders', 'products'.
            fetch_fn: Optional custom fetch function. If None, uses adapter's method.
        """
        from django_bapp_connectors.services.connection import ConnectionService

        sync_state.mark_running()
        result = SyncResult()

        try:
            adapter = ConnectionService.get_adapter(connection)

            if fetch_fn:
                paginated = fetch_fn(adapter, cursor=sync_state.cursor)
            else:
                method = getattr(adapter, f"get_{resource_type}", None)
                if method is None:
                    raise AttributeError(f"Adapter has no method 'get_{resource_type}'")
                paginated = method(cursor=sync_state.cursor or None)

            result.items_fetched = len(paginated.items)
            result.cursor = paginated.cursor or ""
            result.has_more = paginated.has_more

            sync_state.mark_completed(
                cursor=result.cursor,
                last_sync_at=timezone.now(),
            )
        except Exception as e:
            logger.exception("Sync failed for %s on connection %s", resource_type, connection.pk)
            sync_state.mark_failed(str(e))
            result.errors.append(str(e))

        return result

    @staticmethod
    def full_resync(connection, sync_state, resource_type: str, fetch_fn=None) -> SyncResult:
        """Reset cursor and run a full resync."""
        sync_state.cursor = ""
        sync_state.save(update_fields=["cursor", "updated_at"])
        return SyncService.incremental_sync(connection, sync_state, resource_type, fetch_fn)
