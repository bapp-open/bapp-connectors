"""
Admin configuration for connector models.

Since models are abstract, this provides mixin classes for your concrete admin.

Usage:
    from django_bapp_connectors.admin import ConnectionAdminMixin

    @admin.register(MyConnection)
    class MyConnectionAdmin(ConnectionAdminMixin, admin.ModelAdmin):
        pass
"""

from __future__ import annotations


class ConnectionAdminMixin:
    """Admin mixin for AbstractConnection subclasses."""

    list_display = ["display_name", "provider_family", "provider_name", "is_enabled", "is_connected", "updated_at"]
    list_filter = ["provider_family", "provider_name", "is_enabled", "is_connected"]
    search_fields = ["display_name", "provider_name"]
    readonly_fields = ["created_at", "updated_at", "is_connected"]


class SyncStateAdminMixin:
    """Admin mixin for AbstractSyncState subclasses."""

    list_display = ["resource_type", "status", "error_count", "last_sync_at", "updated_at"]
    list_filter = ["status", "resource_type"]
    readonly_fields = ["created_at", "updated_at"]


class WebhookEventAdminMixin:
    """Admin mixin for AbstractWebhookEvent subclasses."""

    list_display = ["provider", "event_type", "status", "signature_valid", "created_at"]
    list_filter = ["provider", "event_type", "status", "signature_valid"]
    search_fields = ["idempotency_key"]
    readonly_fields = ["created_at", "processed_at"]


class ExecutionLogAdminMixin:
    """Admin mixin for AbstractExecutionLog subclasses."""

    list_display = ["action", "method", "response_status", "duration_ms", "created_at"]
    list_filter = ["method", "response_status"]
    search_fields = ["action", "url"]
    readonly_fields = ["created_at"]
