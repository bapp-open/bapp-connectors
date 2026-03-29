"""Tests for django_bapp_connectors.tasks helper functions and Celery tasks."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from bapp_connectors.core.errors import AuthenticationError

from .testapp.models import Connection, WebhookEvent


# ── Celery stub ──
# Celery is not installed in the test environment. We inject a fake celery
# module so that `from celery import shared_task` succeeds inside tasks.py
# and the task functions are defined as plain callables.


def _identity_decorator(**task_kwargs):
    """A no-op decorator that replaces @shared_task."""
    def wrapper(fn):
        return fn
    return wrapper


def _identity_decorator_no_args(fn):
    """Handles @shared_task without parentheses."""
    return fn


class _FakeSharedTask:
    """Callable that works both as @shared_task and @shared_task(...)."""

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            # @shared_task without parentheses
            return args[0]
        # @shared_task(...) with keyword arguments
        def wrapper(fn):
            return fn
        return wrapper


@pytest.fixture(autouse=True, scope="module")
def _stub_celery():
    """Install a fake celery module for the duration of this test module."""
    fake_celery = ModuleType("celery")
    fake_celery.shared_task = _FakeSharedTask()
    sys.modules["celery"] = fake_celery

    # Force re-import of tasks so the Celery branch executes
    if "django_bapp_connectors.tasks" in sys.modules:
        del sys.modules["django_bapp_connectors.tasks"]

    import django_bapp_connectors.tasks  # noqa: F401

    yield

    # Cleanup: remove fake celery and force re-import next time
    del sys.modules["celery"]
    if "django_bapp_connectors.tasks" in sys.modules:
        del sys.modules["django_bapp_connectors.tasks"]


def _import_tasks():
    """Import tasks module (already stubbed by the autouse fixture)."""
    import django_bapp_connectors.tasks as tasks_mod
    return tasks_mod


# ── Fixtures ──


@pytest.fixture
def operational_connection(db):
    return Connection.objects.create(
        provider_family="shop",
        provider_name="woocommerce",
        display_name="Test Shop",
        is_enabled=True,
        is_connected=True,
    )


@pytest.fixture
def non_operational_connection(db):
    return Connection.objects.create(
        provider_family="shop",
        provider_name="woocommerce",
        display_name="Disabled Shop",
        is_enabled=False,
        is_connected=False,
    )


@pytest.fixture
def webhook_event(operational_connection):
    return WebhookEvent.objects.create(
        connection=operational_connection,
        provider="woocommerce",
        event_type="order.created",
        idempotency_key="task-test-key-001",
        payload={"id": 42},
        headers={"Content-Type": "application/json"},
        signature_valid=True,
        status="received",
    )


# ── _get_connection ──


class TestGetConnection:
    def test_resolves_model_and_fetches_by_pk(self, operational_connection):
        tasks = _import_tasks()
        result = tasks._get_connection("testapp", "connection", operational_connection.pk)
        assert result.pk == operational_connection.pk
        assert result.provider_name == "woocommerce"

    def test_raises_value_error_when_app_label_empty(self):
        tasks = _import_tasks()
        with pytest.raises(ValueError, match="app_label and model_name are required"):
            tasks._get_connection("", "connection", 1)

    def test_raises_value_error_when_model_name_empty(self):
        tasks = _import_tasks()
        with pytest.raises(ValueError, match="app_label and model_name are required"):
            tasks._get_connection("testapp", "", 1)

    def test_raises_does_not_exist_for_invalid_pk(self, db):
        tasks = _import_tasks()
        with pytest.raises(Connection.DoesNotExist):
            tasks._get_connection("testapp", "connection", 99999)


# ── _guard_operational ──


class TestGuardOperational:
    def test_returns_true_for_operational_connection(self, operational_connection):
        tasks = _import_tasks()
        assert tasks._guard_operational(operational_connection) is True

    def test_returns_false_for_non_operational_connection(self, non_operational_connection):
        tasks = _import_tasks()
        assert tasks._guard_operational(non_operational_connection) is False


# ── _handle_auth_error ──


class TestHandleAuthError:
    def test_records_failure_for_authentication_error(self, operational_connection):
        tasks = _import_tasks()
        error = AuthenticationError("bad token")
        tasks._handle_auth_error(operational_connection, error)

        operational_connection.refresh_from_db()
        assert operational_connection.auth_failure_count == 1
        assert operational_connection.is_connected is False

    def test_does_nothing_for_non_authentication_error(self, operational_connection):
        tasks = _import_tasks()
        error = RuntimeError("some other error")
        tasks._handle_auth_error(operational_connection, error)

        operational_connection.refresh_from_db()
        assert operational_connection.auth_failure_count == 0
        assert operational_connection.is_connected is True


# ── execute_adapter_method ──


class TestExecuteAdapterMethod:
    @patch.object(Connection, "get_adapter")
    def test_calls_adapter_method_and_returns_result(self, mock_get_adapter, operational_connection):
        tasks = _import_tasks()
        mock_adapter = MagicMock()
        mock_adapter.get_orders.return_value = [{"id": 1}]
        mock_get_adapter.return_value = mock_adapter

        result = tasks.execute_adapter_method(
            connection_id=operational_connection.pk,
            method_name="get_orders",
            app_label="testapp",
            model_name="connection",
        )

        assert result == [{"id": 1}]
        mock_adapter.get_orders.assert_called_once()

    @patch.object(Connection, "get_adapter")
    def test_skips_when_not_operational(self, mock_get_adapter, non_operational_connection):
        tasks = _import_tasks()
        result = tasks.execute_adapter_method(
            connection_id=non_operational_connection.pk,
            method_name="get_orders",
            app_label="testapp",
            model_name="connection",
        )

        assert result is None
        mock_get_adapter.assert_not_called()

    @patch.object(Connection, "get_adapter")
    def test_marks_connected_on_success(self, mock_get_adapter, operational_connection):
        tasks = _import_tasks()

        # Simulate a connection that is operational but is_connected=False
        # (e.g. was just re-enabled). We set is_connected=False directly
        # on the DB but keep is_enabled=True, then make the task fetch
        # it with is_connected=True so it passes the guard.
        # The task code checks `if not connection.is_connected` after success.
        mock_adapter = MagicMock()
        mock_adapter.do_something.return_value = "ok"
        mock_get_adapter.return_value = mock_adapter

        tasks.execute_adapter_method(
            connection_id=operational_connection.pk,
            method_name="do_something",
            app_label="testapp",
            model_name="connection",
        )

        operational_connection.refresh_from_db()
        assert operational_connection.is_connected is True
        assert operational_connection.auth_failure_count == 0


# ── process_webhook ──


class TestProcessWebhook:
    @patch.object(Connection, "get_adapter")
    def test_parses_webhook_marks_processed_and_emits_signal(self, mock_get_adapter, webhook_event, operational_connection):
        tasks = _import_tasks()

        from bapp_connectors.core.dto.webhook import WebhookEvent as WebhookEventDTO
        from bapp_connectors.core.dto.webhook import WebhookEventType

        mock_adapter = MagicMock()
        mock_dto = WebhookEventDTO(
            event_id="42",
            event_type=WebhookEventType.ORDER_CREATED,
            provider="woocommerce",
            provider_event_type="order.created",
            payload={"id": 42},
        )
        mock_adapter.parse_webhook.return_value = mock_dto
        mock_get_adapter.return_value = mock_adapter

        received_signals = []

        def handler(sender, **kwargs):
            received_signals.append(kwargs)

        from django_bapp_connectors.signals import webhook_event_processed

        webhook_event_processed.connect(handler)
        try:
            tasks.process_webhook(
                webhook_event_id=webhook_event.pk,
                app_label="testapp",
                model_name="webhookevent",
            )

            webhook_event.refresh_from_db()
            assert webhook_event.status == "processed"
            assert webhook_event.processed_at is not None
            assert len(received_signals) == 1
            assert received_signals[0]["provider_family"] == "shop"
            assert received_signals[0]["provider_name"] == "woocommerce"
        finally:
            webhook_event_processed.disconnect(handler)

    @patch.object(Connection, "get_adapter")
    def test_marks_failed_on_error(self, mock_get_adapter, webhook_event, operational_connection):
        tasks = _import_tasks()

        mock_adapter = MagicMock()
        mock_adapter.parse_webhook.side_effect = RuntimeError("parse failed")
        mock_get_adapter.return_value = mock_adapter

        with pytest.raises(RuntimeError, match="parse failed"):
            tasks.process_webhook(
                webhook_event_id=webhook_event.pk,
                app_label="testapp",
                model_name="webhookevent",
            )

        webhook_event.refresh_from_db()
        assert webhook_event.status == "failed"
        assert "parse failed" in webhook_event.error
