"""
Django signals emitted by django-bapp-connectors.

All signals use send_robust() at their emission points so that
receiver errors never break framework operations (circuit breaker,
sync, webhook processing).

Usage example::

    from django.dispatch import receiver
    from django_bapp_connectors.signals import webhook_event_processed

    @receiver(webhook_event_processed, dispatch_uid="handle_shop_webhooks")
    def handle_webhook(sender, webhook_event, webhook_dto, connection, event_type, **kwargs):
        if event_type == "order.created":
            process_new_order(webhook_dto.payload, connection)
"""

from django.dispatch import Signal

# ── Webhook signals ──

webhook_event_received = Signal()
"""
Fired when a webhook is received and persisted, before async processing.

Kwargs:
    sender: The concrete WebhookEvent model class.
    webhook_event: The WebhookEvent model instance.
    connection: The Connection model instance (or None).
    provider_family: str (e.g. "shop", "payment").
    provider_name: str (e.g. "woocommerce", "stripe").
"""

webhook_event_processed = Signal()
"""
Fired after a webhook is successfully parsed by the adapter.

This is the primary signal for consuming apps to react to provider events
like "order.created", "payment.completed", etc.

Kwargs:
    sender: The concrete WebhookEvent model class.
    webhook_event: The WebhookEvent model instance (status="processed").
    webhook_dto: The parsed bapp_connectors.core.dto.webhook.WebhookEvent DTO.
    connection: The Connection model instance.
    event_type: str — the normalized event type (e.g. "order.created").
    provider_family: str.
    provider_name: str.
"""

# ── Connection signals ──

connection_status_changed = Signal()
"""
Fired when a connection's is_connected or is_enabled state changes.

Covers both positive transitions (recovery after fix) and negative
transitions (auth failure, auto-disable).

Kwargs:
    sender: The concrete Connection model class.
    connection: The Connection model instance.
    provider_family: str.
    provider_name: str.
    is_connected: bool — new state.
    is_enabled: bool — new state.
    previous_connected: bool — state before this change.
    previous_enabled: bool — state before this change.
"""

connection_disabled = Signal()
"""
Fired when the circuit breaker auto-disables a connection after
reaching the auth failure threshold (3 consecutive failures).

Kwargs:
    sender: The concrete Connection model class.
    connection: The Connection model instance.
    provider_family: str.
    provider_name: str.
    auth_failure_count: int.
    reason: str — the disabled_reason.
"""

# ── Sync signals ──

sync_completed = Signal()
"""
Fired after a sync operation completes successfully.

Kwargs:
    sender: The concrete SyncState model class.
    connection: The Connection model instance.
    sync_state: The SyncState model instance.
    sync_result: The SyncResult dataclass.
    resource_type: str (e.g. "orders", "products").
    is_full_resync: bool.
    provider_family: str.
    provider_name: str.
"""

# ── Email signals ──

email_received = Signal()
"""
Fired once per email fetched during an inbox poll (see services.InboxPollService).

A receiver MAY return a bapp_connectors.core.dto.InboxAction (delete / move /
mark_read). The first non-None action returned by any receiver (in receiver
registration order) is applied to the message; other returned actions are
ignored. Receivers that raise are logged and skipped (send_robust).

Kwargs:
    sender: The concrete Connection model class.
    connection: The Connection model instance.
    email: bapp_connectors.core.dto.EmailDetail — the fully-hydrated message
           (body, headers, attachment manifest). Attachment bytes are fetched
           on demand via connection.get_adapter().download_attachment(...).
    folder: str — the mailbox folder polled.
    provider_family: str ("email").
    provider_name: str (e.g. "gmail", "smtp").
"""
