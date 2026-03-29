"""Concrete model implementations for testing."""

from django.db import models

from django_bapp_connectors.models import (
    AbstractConnection,
    AbstractExecutionLog,
    AbstractSyncState,
    AbstractWebhookEvent,
)


class Connection(AbstractConnection):
    class Meta:
        app_label = "testapp"


class SyncState(AbstractSyncState):
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="sync_states")

    class Meta:
        app_label = "testapp"


class WebhookEvent(AbstractWebhookEvent):
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, null=True, related_name="webhook_events")

    class Meta:
        app_label = "testapp"


class ExecutionLog(AbstractExecutionLog):
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="execution_logs")

    class Meta:
        app_label = "testapp"
