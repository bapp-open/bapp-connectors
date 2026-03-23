"""
Celery tasks for connector operations.

All tasks check connection.is_operational before running and handle
AuthenticationError by recording failures on the connection (circuit breaker).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_connection(app_label: str, model_name: str, connection_id: int):
    """Resolve and fetch a connection model instance."""
    from django.apps import apps

    if not app_label or not model_name:
        raise ValueError("app_label and model_name are required to resolve the Connection model.")

    ConnectionModel = apps.get_model(app_label, model_name)
    return ConnectionModel.objects.get(pk=connection_id)


def _guard_operational(connection) -> bool:
    """
    Check if a connection is operational before running a task.
    Returns False and logs a warning if not.
    """
    if not connection.is_operational:
        logger.warning(
            "Skipping task for connection %s (%s/%s): not operational (enabled=%s, connected=%s, reason=%s)",
            connection.pk,
            connection.provider_family,
            connection.provider_name,
            connection.is_enabled,
            connection.is_connected,
            connection.disabled_reason,
        )
        return False
    return True


def _handle_auth_error(connection, error: Exception) -> None:
    """If the error is an AuthenticationError, record it on the connection."""
    from bapp_connectors.core.errors import AuthenticationError

    if isinstance(error, AuthenticationError):
        connection.record_auth_failure(str(error))
        logger.warning(
            "Auth failure recorded for connection %s (%s/%s): %s (count: %d)",
            connection.pk,
            connection.provider_family,
            connection.provider_name,
            error,
            connection.auth_failure_count,
        )


try:
    from celery import shared_task

    @shared_task(soft_time_limit=180, time_limit=240)
    def execute_adapter_method(connection_id: int, method_name: str, app_label: str = "", model_name: str = "", **kwargs):
        """
        Execute a method on a connection's adapter.

        Checks is_operational first. Records auth failures for circuit breaking.
        """
        connection = _get_connection(app_label, model_name, connection_id)

        if not _guard_operational(connection):
            return None

        try:
            adapter = connection.get_adapter()
            result = getattr(adapter, method_name)(**kwargs)
            # Successful call — ensure connection is marked as connected
            if not connection.is_connected:
                connection.mark_connected()
            return result
        except Exception as e:
            _handle_auth_error(connection, e)
            raise

    @shared_task(soft_time_limit=300, time_limit=360)
    def incremental_sync(connection_id: int, resource_type: str, app_label: str = "", model_name: str = "", sync_state_app: str = "", sync_state_model: str = ""):
        """Run incremental sync. Skips if connection not operational."""
        from django.apps import apps

        from django_bapp_connectors.services.sync import SyncService

        connection = _get_connection(app_label, model_name, connection_id)

        if not _guard_operational(connection):
            return None

        SyncStateModel = apps.get_model(sync_state_app, sync_state_model)
        sync_state, _ = SyncStateModel.objects.get_or_create(
            connection=connection,
            resource_type=resource_type,
            defaults={"status": "idle"},
        )

        try:
            result = SyncService.incremental_sync(connection, sync_state, resource_type)
            if not connection.is_connected:
                connection.mark_connected()
            return result
        except Exception as e:
            _handle_auth_error(connection, e)
            raise

    @shared_task(soft_time_limit=600, time_limit=660)
    def full_resync(connection_id: int, resource_type: str, app_label: str = "", model_name: str = "", sync_state_app: str = "", sync_state_model: str = ""):
        """Run full resync. Skips if connection not operational."""
        from django.apps import apps

        from django_bapp_connectors.services.sync import SyncService

        connection = _get_connection(app_label, model_name, connection_id)

        if not _guard_operational(connection):
            return None

        SyncStateModel = apps.get_model(sync_state_app, sync_state_model)
        sync_state, _ = SyncStateModel.objects.get_or_create(
            connection=connection,
            resource_type=resource_type,
            defaults={"status": "idle"},
        )

        try:
            result = SyncService.full_resync(connection, sync_state, resource_type)
            if not connection.is_connected:
                connection.mark_connected()
            return result
        except Exception as e:
            _handle_auth_error(connection, e)
            raise

    @shared_task
    def process_webhook(webhook_event_id: int, app_label: str = "", model_name: str = ""):
        """Process a persisted webhook event."""
        from django.apps import apps

        WebhookEventModel = apps.get_model(app_label, model_name)
        event = WebhookEventModel.objects.get(pk=webhook_event_id)
        event.mark_processing()

        try:
            if hasattr(event, "connection") and event.connection:
                adapter = event.connection.get_adapter()
                if hasattr(adapter, "parse_webhook"):
                    adapter.parse_webhook(event.headers, event.payload)
            event.mark_processed()
        except Exception as e:
            event.mark_failed(str(e))
            if hasattr(event, "connection") and event.connection:
                _handle_auth_error(event.connection, e)
            raise

except ImportError:
    logger.debug("Celery not installed — async tasks unavailable.")
