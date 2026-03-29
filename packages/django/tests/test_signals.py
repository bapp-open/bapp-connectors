"""Tests for django_bapp_connectors signals."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from django_bapp_connectors.signals import (
    connection_disabled,
    connection_status_changed,
    sync_completed,
    webhook_event_processed,
    webhook_event_received,
)

from .testapp.models import Connection, SyncState, WebhookEvent


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
def disconnected_connection(db):
    return Connection.objects.create(
        provider_family="shop",
        provider_name="gomag",
        display_name="Disconnected Shop",
        is_enabled=True,
        is_connected=False,
    )


@pytest.fixture
def sync_state(connection):
    return SyncState.objects.create(
        connection=connection,
        resource_type="orders",
        status="idle",
    )


@pytest.fixture
def webhook_event(connection):
    return WebhookEvent.objects.create(
        connection=connection,
        provider="woocommerce",
        event_type="order.created",
        idempotency_key="test-key-123",
        payload={"id": 42},
        headers={"Content-Type": "application/json"},
        signature_valid=True,
        status="received",
    )


# ── connection_status_changed ──


class TestConnectionStatusChangedSignal:
    def test_emitted_on_mark_connected(self, disconnected_connection):
        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        connection_status_changed.connect(handler)
        try:
            disconnected_connection.mark_connected()

            assert len(received) == 1
            assert received[0]["is_connected"] is True
            assert received[0]["previous_connected"] is False
            assert received[0]["provider_family"] == "shop"
            assert received[0]["provider_name"] == "gomag"
        finally:
            connection_status_changed.disconnect(handler)

    def test_emitted_on_auth_failure(self, connection):
        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        connection_status_changed.connect(handler)
        try:
            connection.record_auth_failure("bad token")

            assert len(received) == 1
            assert received[0]["is_connected"] is False
            assert received[0]["previous_connected"] is True
        finally:
            connection_status_changed.disconnect(handler)

    def test_not_emitted_when_state_unchanged(self, disconnected_connection):
        """If already disconnected, recording another failure should not emit."""
        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        connection_status_changed.connect(handler)
        try:
            disconnected_connection.record_auth_failure("still bad")
            assert len(received) == 0
        finally:
            connection_status_changed.disconnect(handler)

    def test_emitted_on_re_enable(self, db):
        conn = Connection.objects.create(
            provider_family="courier",
            provider_name="gls",
            is_enabled=False,
            is_connected=False,
        )
        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        connection_status_changed.connect(handler)
        try:
            conn.re_enable()

            assert len(received) == 1
            assert received[0]["is_enabled"] is True
            assert received[0]["previous_enabled"] is False
        finally:
            connection_status_changed.disconnect(handler)

    def test_sender_is_concrete_model_class(self, disconnected_connection):
        senders = []

        def handler(sender, **kwargs):
            senders.append(sender)

        connection_status_changed.connect(handler)
        try:
            disconnected_connection.mark_connected()
            assert senders[0] is Connection
        finally:
            connection_status_changed.disconnect(handler)


# ── connection_disabled ──


class TestConnectionDisabledSignal:
    def test_emitted_on_threshold(self, connection):
        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        connection_disabled.connect(handler)
        try:
            # First two failures — no disable signal
            connection.record_auth_failure("fail 1")
            connection.record_auth_failure("fail 2")
            assert len(received) == 0

            # Third failure — threshold reached
            connection.record_auth_failure("fail 3")
            assert len(received) == 1
            assert received[0]["auth_failure_count"] == 3
            assert "fail 3" in received[0]["reason"]
            assert received[0]["provider_family"] == "shop"
        finally:
            connection_disabled.disconnect(handler)

    def test_not_emitted_below_threshold(self, connection):
        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        connection_disabled.connect(handler)
        try:
            connection.record_auth_failure("fail 1")
            connection.record_auth_failure("fail 2")
            assert len(received) == 0
        finally:
            connection_disabled.disconnect(handler)


# ── sync_completed ──


class TestSyncCompletedSignal:
    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_emitted_on_successful_sync(self, mock_get_adapter, connection, sync_state):
        from bapp_connectors.core.dto import PaginatedResult

        mock_adapter = MagicMock()
        mock_adapter.get_orders.return_value = PaginatedResult(
            items=[{"id": 1}],
            cursor="2",
            has_more=True,
            total=10,
        )
        mock_get_adapter.return_value = mock_adapter

        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        sync_completed.connect(handler)
        try:
            from django_bapp_connectors.services.sync import SyncService

            SyncService.incremental_sync(connection, sync_state, "orders")

            assert len(received) == 1
            assert received[0]["resource_type"] == "orders"
            assert received[0]["is_full_resync"] is False
            assert received[0]["provider_family"] == "shop"
            assert received[0]["sync_result"].items_fetched == 1
            assert received[0]["connection"] == connection
            assert received[0]["sync_state"] == sync_state
        finally:
            sync_completed.disconnect(handler)

    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_full_resync_flag(self, mock_get_adapter, connection, sync_state):
        from bapp_connectors.core.dto import PaginatedResult

        mock_adapter = MagicMock()
        mock_adapter.get_orders.return_value = PaginatedResult(
            items=[], cursor="", has_more=False, total=0,
        )
        mock_get_adapter.return_value = mock_adapter

        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        sync_completed.connect(handler)
        try:
            from django_bapp_connectors.services.sync import SyncService

            SyncService.full_resync(connection, sync_state, "orders")

            assert len(received) == 1
            assert received[0]["is_full_resync"] is True
        finally:
            sync_completed.disconnect(handler)

    @patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter")
    def test_not_emitted_on_failure(self, mock_get_adapter, connection, sync_state):
        mock_adapter = MagicMock()
        mock_adapter.get_orders.side_effect = Exception("API down")
        mock_get_adapter.return_value = mock_adapter

        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        sync_completed.connect(handler)
        try:
            from django_bapp_connectors.services.sync import SyncService

            result = SyncService.incremental_sync(connection, sync_state, "orders")

            assert len(received) == 0
            assert len(result.errors) == 1
        finally:
            sync_completed.disconnect(handler)


# ── webhook_event_received ──


class TestWebhookEventReceivedSignal:
    def test_emitted_on_receive(self, connection):
        from django_bapp_connectors.services.webhook import WebhookService

        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        webhook_event_received.connect(handler)
        try:
            service = WebhookService(webhook_event_model=WebhookEvent)
            service.receive(
                provider="woocommerce",
                headers={"Content-Type": "application/json"},
                body=b'{"id": 99}',
                connection=connection,
            )

            assert len(received) == 1
            assert received[0]["provider_family"] == "shop"
            assert received[0]["provider_name"] == "woocommerce"
            assert received[0]["connection"] == connection
            assert received[0]["webhook_event"].provider == "woocommerce"
        finally:
            webhook_event_received.disconnect(handler)

    def test_not_emitted_for_duplicates(self, connection):
        from django_bapp_connectors.services.webhook import WebhookService

        service = WebhookService(webhook_event_model=WebhookEvent)

        # First receive
        service.receive(
            provider="woocommerce",
            headers={},
            body=b'{"id": 100}',
            connection=connection,
        )

        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        webhook_event_received.connect(handler)
        try:
            # Same body = same idempotency key = duplicate
            service.receive(
                provider="woocommerce",
                headers={},
                body=b'{"id": 100}',
                connection=connection,
            )

            assert len(received) == 0
        finally:
            webhook_event_received.disconnect(handler)


# ── webhook_event_processed ──


class TestWebhookEventProcessedSignal:
    def test_emitted_after_processing(self, webhook_event, connection):
        from bapp_connectors.core.dto.webhook import WebhookEvent as WebhookEventDTO
        from bapp_connectors.core.dto.webhook import WebhookEventType

        mock_dto = WebhookEventDTO(
            event_id="42",
            event_type=WebhookEventType.ORDER_CREATED,
            provider="woocommerce",
            provider_event_type="order.created",
            payload={"id": 42},
        )

        received = []

        def handler(sender, **kwargs):
            received.append(kwargs)

        webhook_event_processed.connect(handler)
        try:
            # Simulate what process_webhook task does
            from django_bapp_connectors.signals import webhook_event_processed as sig

            webhook_event.mark_processing()
            webhook_event.mark_processed()

            sig.send_robust(
                sender=type(webhook_event),
                webhook_event=webhook_event,
                webhook_dto=mock_dto,
                connection=connection,
                event_type="order.created",
                provider_family="shop",
                provider_name="woocommerce",
            )

            assert len(received) == 1
            assert received[0]["event_type"] == "order.created"
            assert received[0]["webhook_dto"].event_type == WebhookEventType.ORDER_CREATED
            assert received[0]["connection"] == connection
        finally:
            webhook_event_processed.disconnect(handler)


# ── Signal robustness ──


class TestSignalRobustness:
    def test_receiver_error_does_not_break_mark_connected(self, disconnected_connection):
        """send_robust ensures a broken receiver doesn't break the model method."""

        def broken_handler(sender, **kwargs):
            raise RuntimeError("receiver crashed")

        connection_status_changed.connect(broken_handler)
        try:
            # Should not raise even though the receiver does
            disconnected_connection.mark_connected()

            disconnected_connection.refresh_from_db()
            assert disconnected_connection.is_connected is True
        finally:
            connection_status_changed.disconnect(broken_handler)

    def test_receiver_error_does_not_break_record_auth_failure(self, connection):
        """send_robust ensures a broken receiver doesn't break circuit breaker."""

        def broken_handler(sender, **kwargs):
            raise RuntimeError("receiver crashed")

        connection_status_changed.connect(broken_handler)
        try:
            connection.record_auth_failure("test")

            connection.refresh_from_db()
            assert connection.is_connected is False
            assert connection.auth_failure_count == 1
        finally:
            connection_status_changed.disconnect(broken_handler)
