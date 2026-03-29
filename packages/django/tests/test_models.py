"""Tests for abstract model methods via concrete test models."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

import pytest

from .testapp.models import Connection, ExecutionLog, SyncState, WebhookEvent


# ── Fixtures ──


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
        provider_family="courier",
        provider_name="gls",
        display_name="Disconnected Courier",
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
        idempotency_key="unique-key-001",
        payload={"id": 1},
        headers={"Content-Type": "application/json"},
        signature_valid=True,
        status="received",
    )


# ── Connection model ──


class TestConnectionIsOperational:
    def test_returns_true_when_enabled_and_connected(self, connection):
        assert connection.is_operational is True

    def test_returns_false_when_not_enabled(self, db):
        conn = Connection.objects.create(
            provider_family="shop",
            provider_name="prestashop",
            is_enabled=False,
            is_connected=True,
        )
        assert conn.is_operational is False

    def test_returns_false_when_not_connected(self, disconnected_connection):
        assert disconnected_connection.is_operational is False

    def test_returns_false_when_neither(self, db):
        conn = Connection.objects.create(
            provider_family="shop",
            provider_name="prestashop",
            is_enabled=False,
            is_connected=False,
        )
        assert conn.is_operational is False


class TestConnectionCredentials:
    def test_round_trip_encrypt_decrypt(self, connection):
        creds = {"api_key": "sk-test-123", "api_secret": "secret456"}
        connection.credentials = creds
        connection.save()

        connection.refresh_from_db()
        assert connection.credentials == creds

    def test_getter_returns_empty_dict_when_no_encrypted_data(self, db):
        conn = Connection.objects.create(
            provider_family="payment",
            provider_name="stripe",
            credentials_encrypted="",
        )
        assert conn.credentials == {}

    def test_setter_encrypts_value(self, connection):
        connection.credentials = {"token": "abc"}
        # The encrypted field should not be empty and should differ from plaintext
        assert connection.credentials_encrypted != ""
        assert "abc" not in connection.credentials_encrypted


class TestConnectionStr:
    def test_str_with_display_name(self, connection):
        result = str(connection)
        assert "Test Shop" in result
        assert "shop" in result

    def test_str_without_display_name(self, db):
        conn = Connection.objects.create(
            provider_family="courier",
            provider_name="sameday",
            display_name="",
        )
        result = str(conn)
        assert "sameday" in result
        assert "courier" in result


class TestConnectionRecordAuthFailure:
    def test_increments_failure_count(self, connection):
        connection.record_auth_failure("bad token")
        connection.refresh_from_db()
        assert connection.auth_failure_count == 1

    def test_sets_last_auth_failure_at(self, connection):
        assert connection.last_auth_failure_at is None
        connection.record_auth_failure("expired")
        connection.refresh_from_db()
        assert connection.last_auth_failure_at is not None

    def test_sets_is_connected_false(self, connection):
        assert connection.is_connected is True
        connection.record_auth_failure("unauthorized")
        connection.refresh_from_db()
        assert connection.is_connected is False

    def test_truncates_reason_in_disabled_reason(self, connection):
        long_reason = "x" * 600
        # Push to threshold
        connection.record_auth_failure("fail 1")
        connection.record_auth_failure("fail 2")
        connection.record_auth_failure(long_reason)
        connection.refresh_from_db()
        # The reason is embedded after a prefix; the raw reason is truncated to 400 chars
        assert long_reason[:400] in connection.disabled_reason
        assert long_reason[:401] not in connection.disabled_reason

    def test_disables_at_threshold(self, connection):
        connection.record_auth_failure("fail 1")
        connection.record_auth_failure("fail 2")
        connection.refresh_from_db()
        assert connection.is_enabled is True

        connection.record_auth_failure("fail 3")
        connection.refresh_from_db()
        assert connection.is_enabled is False
        assert connection.auth_failure_count == 3
        assert connection.disabled_reason != ""


class TestConnectionMarkConnected:
    def test_resets_auth_failure_count(self, disconnected_connection):
        disconnected_connection.auth_failure_count = 2
        disconnected_connection.save()
        disconnected_connection.mark_connected()
        disconnected_connection.refresh_from_db()
        assert disconnected_connection.auth_failure_count == 0

    def test_clears_last_auth_failure_at(self, disconnected_connection):
        disconnected_connection.record_auth_failure("err")
        disconnected_connection.mark_connected()
        disconnected_connection.refresh_from_db()
        assert disconnected_connection.last_auth_failure_at is None

    def test_clears_disabled_reason(self, disconnected_connection):
        disconnected_connection.disabled_reason = "was broken"
        disconnected_connection.save()
        disconnected_connection.mark_connected()
        disconnected_connection.refresh_from_db()
        assert disconnected_connection.disabled_reason == ""

    def test_sets_is_connected_true(self, disconnected_connection):
        assert disconnected_connection.is_connected is False
        disconnected_connection.mark_connected()
        disconnected_connection.refresh_from_db()
        assert disconnected_connection.is_connected is True


class TestConnectionReEnable:
    def test_sets_is_enabled_true(self, db):
        conn = Connection.objects.create(
            provider_family="shop",
            provider_name="emag",
            is_enabled=False,
            is_connected=False,
        )
        conn.re_enable()
        conn.refresh_from_db()
        assert conn.is_enabled is True

    def test_resets_auth_failure_count(self, db):
        conn = Connection.objects.create(
            provider_family="shop",
            provider_name="emag",
            is_enabled=False,
            auth_failure_count=5,
        )
        conn.re_enable()
        conn.refresh_from_db()
        assert conn.auth_failure_count == 0

    def test_clears_disabled_reason(self, db):
        conn = Connection.objects.create(
            provider_family="shop",
            provider_name="emag",
            is_enabled=False,
            disabled_reason="auto-disabled",
        )
        conn.re_enable()
        conn.refresh_from_db()
        assert conn.disabled_reason == ""


# ── SyncState model ──


class TestSyncStateMarkRunning:
    def test_sets_status_running(self, sync_state):
        sync_state.mark_running()
        sync_state.refresh_from_db()
        assert sync_state.status == "running"


class TestSyncStateMarkCompleted:
    def test_sets_status_completed(self, sync_state):
        sync_state.mark_completed(cursor="page-2")
        sync_state.refresh_from_db()
        assert sync_state.status == "completed"

    def test_resets_error_count_and_last_error(self, sync_state):
        sync_state.error_count = 3
        sync_state.last_error = "something broke"
        sync_state.save()

        sync_state.mark_completed()
        sync_state.refresh_from_db()
        assert sync_state.error_count == 0
        assert sync_state.last_error == ""

    def test_sets_cursor(self, sync_state):
        sync_state.mark_completed(cursor="cursor-abc")
        sync_state.refresh_from_db()
        assert sync_state.cursor == "cursor-abc"

    def test_keeps_existing_cursor_when_none_provided(self, sync_state):
        sync_state.cursor = "existing-cursor"
        sync_state.save()

        sync_state.mark_completed()
        sync_state.refresh_from_db()
        assert sync_state.cursor == "existing-cursor"

    def test_sets_last_sync_at(self, sync_state):
        sync_state.mark_completed()
        sync_state.refresh_from_db()
        assert sync_state.last_sync_at is not None

    def test_uses_explicit_last_sync_at(self, sync_state):
        explicit_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=dt_timezone.utc)
        sync_state.mark_completed(last_sync_at=explicit_time)
        sync_state.refresh_from_db()
        assert sync_state.last_sync_at == explicit_time


class TestSyncStateMarkFailed:
    def test_sets_status_failed(self, sync_state):
        sync_state.mark_failed("API timeout")
        sync_state.refresh_from_db()
        assert sync_state.status == "failed"

    def test_increments_error_count(self, sync_state):
        sync_state.mark_failed("error 1")
        sync_state.refresh_from_db()
        assert sync_state.error_count == 1

        sync_state.mark_failed("error 2")
        sync_state.refresh_from_db()
        assert sync_state.error_count == 2

    def test_truncates_error_to_2000_chars(self, sync_state):
        long_error = "e" * 3000
        sync_state.mark_failed(long_error)
        sync_state.refresh_from_db()
        assert len(sync_state.last_error) == 2000


class TestSyncStateStr:
    def test_str_representation(self, sync_state):
        result = str(sync_state)
        assert "orders" in result
        assert "idle" in result


# ── WebhookEvent model ──


class TestWebhookEventIsDuplicate:
    def test_returns_true_when_duplicate(self, webhook_event):
        webhook_event.mark_duplicate()
        assert webhook_event.is_duplicate is True

    def test_returns_false_when_not_duplicate(self, webhook_event):
        assert webhook_event.is_duplicate is False


class TestWebhookEventMarkProcessing:
    def test_sets_status_processing(self, webhook_event):
        webhook_event.mark_processing()
        webhook_event.refresh_from_db()
        assert webhook_event.status == "processing"


class TestWebhookEventMarkProcessed:
    def test_sets_status_processed(self, webhook_event):
        webhook_event.mark_processed()
        webhook_event.refresh_from_db()
        assert webhook_event.status == "processed"

    def test_sets_processed_at(self, webhook_event):
        assert webhook_event.processed_at is None
        webhook_event.mark_processed()
        webhook_event.refresh_from_db()
        assert webhook_event.processed_at is not None


class TestWebhookEventMarkFailed:
    def test_sets_status_failed(self, webhook_event):
        webhook_event.mark_failed("handler error")
        webhook_event.refresh_from_db()
        assert webhook_event.status == "failed"

    def test_sets_error(self, webhook_event):
        webhook_event.mark_failed("something went wrong")
        webhook_event.refresh_from_db()
        assert webhook_event.error == "something went wrong"

    def test_truncates_error_to_2000_chars(self, webhook_event):
        long_error = "w" * 3000
        webhook_event.mark_failed(long_error)
        webhook_event.refresh_from_db()
        assert len(webhook_event.error) == 2000


class TestWebhookEventMarkDuplicate:
    def test_sets_status_duplicate(self, webhook_event):
        webhook_event.mark_duplicate()
        webhook_event.refresh_from_db()
        assert webhook_event.status == "duplicate"


class TestWebhookEventStr:
    def test_str_representation(self, webhook_event):
        result = str(webhook_event)
        assert "woocommerce" in result
        assert "order.created" in result
        assert "received" in result


# ── ExecutionLog model ──


class TestExecutionLog:
    def test_creation_with_all_fields(self, connection):
        log = ExecutionLog.objects.create(
            connection=connection,
            action="get_orders",
            method="GET",
            url="https://shop.example.com/wp-json/wc/v3/orders",
            request_payload={"per_page": 50},
            response_status=200,
            response_payload={"orders": []},
            duration_ms=342,
            error="",
        )
        log.refresh_from_db()
        assert log.action == "get_orders"
        assert log.method == "GET"
        assert log.url == "https://shop.example.com/wp-json/wc/v3/orders"
        assert log.request_payload == {"per_page": 50}
        assert log.response_status == 200
        assert log.response_payload == {"orders": []}
        assert log.duration_ms == 342
        assert log.error == ""
        assert log.created_at is not None

    def test_str_representation(self, connection):
        log = ExecutionLog.objects.create(
            connection=connection,
            action="update_product",
            method="PUT",
            url="https://shop.example.com/api/products/1",
            response_status=200,
        )
        result = str(log)
        assert "update_product" in result
        assert "PUT" in result
        assert "200" in result

    def test_default_ordering_is_newest_first(self):
        """The abstract model defines ordering = ['-created_at']."""
        from django_bapp_connectors.models.execution_log import AbstractExecutionLog

        assert AbstractExecutionLog._meta.ordering == ["-created_at"]
