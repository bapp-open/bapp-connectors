"""Tests for SyncService edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from django_bapp_connectors.services.sync import SyncResult, SyncService

from tests.testapp.models import Connection, SyncState


@pytest.fixture
def connection(db):
    return Connection.objects.create(
        provider_family="shop",
        provider_name="woocommerce",
        display_name="Test Shop",
        is_enabled=True,
        is_connected=True,
    )


@pytest.fixture
def sync_state(connection):
    return SyncState.objects.create(
        connection=connection,
        resource_type="orders",
        status="idle",
        cursor="page_5",
    )


# ── SyncResult defaults ──


class TestSyncResultDefaults:
    def test_defaults_are_correct(self):
        result = SyncResult()

        assert result.items_fetched == 0
        assert result.items_processed == 0
        assert result.cursor == ""
        assert result.has_more is False
        assert result.errors == []

    def test_errors_list_is_independent_per_instance(self):
        """Each SyncResult should get its own errors list, not a shared one."""
        r1 = SyncResult()
        r2 = SyncResult()
        r1.errors.append("boom")

        assert r2.errors == []


# ── incremental_sync with custom fetch_fn ──


class TestIncrementalSyncCustomFetchFn:
    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_uses_custom_fetch_fn(self, mock_get_adapter, connection, sync_state):
        from bapp_connectors.core.dto import PaginatedResult

        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        custom_fn = MagicMock(return_value=PaginatedResult(
            items=[{"id": 1}, {"id": 2}],
            cursor="page_6",
            has_more=True,
            total=100,
        ))

        result = SyncService.incremental_sync(
            connection, sync_state, "orders", fetch_fn=custom_fn,
        )

        custom_fn.assert_called_once_with(mock_adapter, cursor="page_5")
        # The adapter's get_orders should NOT have been called
        mock_adapter.get_orders.assert_not_called()
        assert result.items_fetched == 2
        assert result.cursor == "page_6"
        assert result.has_more is True


# ── incremental_sync when adapter method is missing ──


class TestIncrementalSyncMissingMethod:
    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_missing_adapter_method_marks_failed(self, mock_get_adapter, connection, sync_state):
        mock_adapter = MagicMock(spec=[])  # spec=[] means no attributes at all
        mock_get_adapter.return_value = mock_adapter

        result = SyncService.incremental_sync(connection, sync_state, "widgets")

        sync_state.refresh_from_db()
        assert sync_state.status == "failed"
        assert "get_widgets" in sync_state.last_error
        assert len(result.errors) == 1
        assert "get_widgets" in result.errors[0]


# ── incremental_sync cursor flow ──


class TestIncrementalSyncCursorFlow:
    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_cursor_is_passed_to_adapter(self, mock_get_adapter, connection, sync_state):
        from bapp_connectors.core.dto import PaginatedResult

        mock_adapter = MagicMock()
        mock_adapter.get_orders.return_value = PaginatedResult(
            items=[{"id": 10}],
            cursor="page_6",
            has_more=False,
            total=10,
        )
        mock_get_adapter.return_value = mock_adapter

        # sync_state.cursor was set to "page_5" in the fixture
        SyncService.incremental_sync(connection, sync_state, "orders")

        mock_adapter.get_orders.assert_called_once_with(cursor="page_5")

    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_empty_cursor_passes_none(self, mock_get_adapter, connection, sync_state):
        """When cursor is empty string, it should be passed as None to the adapter."""
        from bapp_connectors.core.dto import PaginatedResult

        sync_state.cursor = ""
        sync_state.save(update_fields=["cursor"])

        mock_adapter = MagicMock()
        mock_adapter.get_orders.return_value = PaginatedResult(
            items=[], cursor="", has_more=False, total=0,
        )
        mock_get_adapter.return_value = mock_adapter

        SyncService.incremental_sync(connection, sync_state, "orders")

        mock_adapter.get_orders.assert_called_once_with(cursor=None)


# ── full_resync ──


class TestFullResync:
    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_resets_cursor_before_calling_incremental(self, mock_get_adapter, connection, sync_state):
        from bapp_connectors.core.dto import PaginatedResult

        mock_adapter = MagicMock()
        mock_adapter.get_orders.return_value = PaginatedResult(
            items=[], cursor="", has_more=False, total=0,
        )
        mock_get_adapter.return_value = mock_adapter

        assert sync_state.cursor == "page_5"

        SyncService.full_resync(connection, sync_state, "orders")

        # Cursor should have been reset to "" before calling adapter
        # Since empty cursor is passed as None to adapter
        mock_adapter.get_orders.assert_called_once_with(cursor=None)

        # Verify cursor was persisted as "" in the DB reset step
        sync_state.refresh_from_db()
        # After a successful sync with empty cursor returned, cursor stays ""
        assert sync_state.cursor == ""
