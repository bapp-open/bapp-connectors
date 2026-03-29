# django-bapp-connectors

Django integration for [bapp-connectors](https://pypi.org/project/bapp-connectors/) — multi-tenant connection management, encrypted credentials, cursor-based sync, circuit breakers, webhooks, and audit logging.

All models are **abstract** — you subclass them and add your own tenant FK (company, organization, user, etc.). The package is completely **family-agnostic**: adding a new provider to `bapp-connectors` requires zero changes here.

## Installation

```bash
pip install django-bapp-connectors
```

With Celery support:

```bash
pip install django-bapp-connectors[celery]
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "django_bapp_connectors",
]
```

## Quick Start

### 1. Define your models

```python
# connectors/models.py
from django.db import models
from django_bapp_connectors.models import (
    AbstractConnection,
    AbstractSyncState,
    AbstractExecutionLog,
    AbstractWebhookEvent,
)


class Connection(AbstractConnection):
    """A provider connection scoped to a company."""
    company = models.ForeignKey("companies.Company", on_delete=models.CASCADE, related_name="connections")

    class Meta:
        unique_together = [("company", "provider_family", "provider_name")]


class SyncState(AbstractSyncState):
    """Tracks sync progress per connection per resource type."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="sync_states")

    class Meta:
        unique_together = [("connection", "resource_type")]


class ExecutionLog(AbstractExecutionLog):
    """Audit trail of every API call made through a connection."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="execution_logs")


class WebhookEvent(AbstractWebhookEvent):
    """Persists incoming webhooks for audit and deduplication."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, null=True, related_name="webhook_events")
```

### 2. Register admin

```python
# connectors/admin.py
from django.contrib import admin
from django_bapp_connectors.admin import (
    ConnectionAdminMixin,
    SyncStateAdminMixin,
    ExecutionLogAdminMixin,
    WebhookEventAdminMixin,
)
from .models import Connection, SyncState, ExecutionLog, WebhookEvent


@admin.register(Connection)
class ConnectionAdmin(ConnectionAdminMixin, admin.ModelAdmin):
    pass

@admin.register(SyncState)
class SyncStateAdmin(SyncStateAdminMixin, admin.ModelAdmin):
    pass

@admin.register(ExecutionLog)
class ExecutionLogAdmin(ExecutionLogAdminMixin, admin.ModelAdmin):
    pass

@admin.register(WebhookEvent)
class WebhookEventAdmin(WebhookEventAdminMixin, admin.ModelAdmin):
    pass
```

### 3. Configure settings

```python
# settings.py
BAPP_CONNECTORS = {
    # Optional: Fernet key for credential encryption.
    # Falls back to deriving one from SECRET_KEY if not set.
    "ENCRYPTION_KEY": "",

    # Base URL for webhook endpoints (used for registering webhooks with providers).
    "WEBHOOK_BASE_URL": "https://yourapp.com/webhooks/",

    # Default HTTP timeout in seconds.
    "DEFAULT_TIMEOUT": 10,

    # Required for the built-in webhook_receiver view to resolve models.
    # Format: "app_label.ModelName"
    "CONNECTION_MODEL": "connectors.Connection",
    "WEBHOOK_EVENT_MODEL": "connectors.WebhookEvent",
}
```

### 4. Wire up webhook URLs

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    # ...
    path("webhooks/", include("django_bapp_connectors.webhooks.urls")),
]
```

This registers two endpoints:

- `webhooks/<connection_id>/<action>/` — generic webhook receiver
- `webhooks/oauth/callback/<provider>/` — OAuth2 callback handler

## Usage

### Creating a connection

```python
from connectors.models import Connection

connection = Connection(
    company=company,
    provider_family="shop",
    provider_name="woocommerce",
    display_name="Main WooCommerce Store",
    config={
        "prices_include_vat": True,
        "vat_rate": "0.19",
        # Custom status mapping (optional)
        "status_map_inbound": {"wc-custom-status": "processing"},
        "status_map_outbound": {"shipped": "wc-custom-shipped"},
    },
)

# Credentials are encrypted at rest using Fernet
connection.credentials = {
    "consumer_key": "ck_...",
    "consumer_secret": "cs_...",
    "store_url": "https://myshop.com",
}
connection.save()
```

### Testing a connection

```python
result = connection.test_connection()
# result.success  -> True/False
# result.message  -> "Connection successful" / error description
# connection.is_connected is updated automatically
```

Or via the service layer:

```python
from django_bapp_connectors.services import ConnectionService

result = ConnectionService.test_connection(connection)
```

### Using an adapter directly

```python
from bapp_connectors.core.dto import OrderStatus

# Get a configured adapter instance
adapter = connection.get_adapter()

# Fetch orders
orders = adapter.get_orders(cursor="1")
for order in orders.items:
    print(f"Order {order.order_id}: {order.status}")

# Fetch products
products = adapter.get_products()
for product in products.items:
    print(f"{product.name} - {product.price} {product.currency}")

# Update order status
updated = adapter.update_order_status("12345", OrderStatus.SHIPPED)
```

### Listing available providers

```python
from django_bapp_connectors.services import ConnectionService

# All providers
providers = ConnectionService.list_available_providers()

# Filter by family
shop_providers = ConnectionService.list_available_providers(family="shop")
```

### Credential rotation

```python
ConnectionService.rotate_credentials(connection, {
    "consumer_key": "ck_new_...",
    "consumer_secret": "cs_new_...",
    "store_url": "https://myshop.com",
})
```

### Settings validation

```python
errors = ConnectionService.validate_settings(connection, {
    "prices_include_vat": True,
    "vat_rate": "not_a_number",
})
if errors:
    print(errors)
else:
    ConnectionService.update_settings(connection, new_config)
```

## Sync

Cursor-based incremental sync with automatic state tracking.

### Incremental sync (one page)

```python
from connectors.models import Connection, SyncState
from django_bapp_connectors.services import SyncService

connection = Connection.objects.get(pk=1)
sync_state, _ = SyncState.objects.get_or_create(
    connection=connection,
    resource_type="orders",
    defaults={"status": "idle"},
)

result = SyncService.incremental_sync(connection, sync_state, "orders")
# result.items_fetched  -> number of items returned
# result.has_more       -> True if there are more pages
# result.cursor         -> saved automatically for next run
# result.errors         -> list of error messages (empty on success)
```

### Full resync

```python
# Resets cursor and syncs from the beginning
result = SyncService.full_resync(connection, sync_state, "orders")
```

### Custom fetch function

```python
def fetch_recent_orders(adapter, cursor=None):
    from datetime import datetime, timedelta, UTC
    since = datetime.now(UTC) - timedelta(days=7)
    return adapter.get_orders(since=since, cursor=cursor)

result = SyncService.incremental_sync(
    connection, sync_state, "orders", fetch_fn=fetch_recent_orders
)
```

## Celery Tasks

All tasks check `connection.is_operational` before running and integrate with the circuit breaker.

```python
from django_bapp_connectors.tasks import (
    execute_adapter_method,
    incremental_sync,
    full_resync,
    process_webhook,
)

# Run any adapter method as a Celery task
execute_adapter_method.delay(
    connection_id=1,
    method_name="get_orders",
    app_label="connectors",
    model_name="Connection",
)

# Incremental sync as a Celery task
incremental_sync.delay(
    connection_id=1,
    resource_type="orders",
    app_label="connectors",
    model_name="Connection",
    sync_state_app="connectors",
    sync_state_model="SyncState",
)

# Full resync
full_resync.delay(
    connection_id=1,
    resource_type="products",
    app_label="connectors",
    model_name="Connection",
    sync_state_app="connectors",
    sync_state_model="SyncState",
)
```

### Periodic sync with Celery Beat

```python
# settings.py
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "sync-orders-every-15-min": {
        "task": "django_bapp_connectors.tasks.incremental_sync",
        "schedule": crontab(minute="*/15"),
        "kwargs": {
            "connection_id": 1,
            "resource_type": "orders",
            "app_label": "connectors",
            "model_name": "Connection",
            "sync_state_app": "connectors",
            "sync_state_model": "SyncState",
        },
    },
}
```

## Circuit Breaker

Connections automatically disable themselves after repeated auth failures to prevent cron loops from hammering a broken provider.

**How it works:**

1. An API call raises `AuthenticationError`
2. `connection.record_auth_failure()` increments `auth_failure_count`
3. After 3 consecutive failures: `is_enabled=False`, `is_connected=False`
4. All Celery tasks check `connection.is_operational` and skip disabled connections
5. Re-enabling requires manual action after fixing credentials:

```python
# After fixing credentials
connection.credentials = {"token": "new_valid_token", ...}
connection.save()
connection.re_enable()  # Resets failure count, sets is_enabled=True
result = connection.test_connection()  # Verify it works
```

## Webhooks

### Receiving webhooks

The built-in `webhook_receiver` view returns 200 immediately. For custom processing, use the `WebhookService`:

```python
from django_bapp_connectors.services import WebhookService
from connectors.models import WebhookEvent

service = WebhookService(webhook_event_model=WebhookEvent)

event = service.receive(
    provider="woocommerce",
    headers=request.headers,
    body=request.body,
    signature_method="hmac-sha256",
    signature_header="X-WC-Webhook-Signature",
    secret=connection.config.get("webhook_secret", ""),
    connection=connection,
)

# event.signature_valid  -> True/False
# event.is_duplicate     -> True if idempotency key already seen
```

### Processing webhooks with Celery

```python
process_webhook.delay(
    webhook_event_id=event.pk,
    app_label="connectors",
    model_name="WebhookEvent",
)
```

## Signals

The package emits Django signals at key lifecycle points. All signals use
`send_robust()` so receiver errors never break framework operations.

```python
from django_bapp_connectors.signals import (
    webhook_event_received,     # Webhook persisted, before async processing
    webhook_event_processed,    # Parsed webhook DTO available (the critical one)
    connection_status_changed,  # Connection went connected/disconnected/enabled/disabled
    connection_disabled,        # Circuit breaker auto-disabled a connection
    sync_completed,             # Sync finished successfully
)
```

### Reacting to webhook events

```python
# receivers.py
from django.dispatch import receiver
from django_bapp_connectors.signals import webhook_event_processed


@receiver(webhook_event_processed, dispatch_uid="handle_shop_orders")
def handle_shop_webhook(sender, webhook_event, webhook_dto, connection, event_type, **kwargs):
    if event_type == "order.created":
        create_local_order(webhook_dto.payload, connection)
    elif event_type == "order.cancelled":
        cancel_local_order(webhook_dto.payload, connection)
```

### Monitoring connection health

```python
from django.dispatch import receiver
from django_bapp_connectors.signals import connection_disabled, connection_status_changed


@receiver(connection_disabled, dispatch_uid="alert_on_disable")
def alert_connection_disabled(sender, connection, reason, auth_failure_count, **kwargs):
    send_admin_alert(
        f"Connection {connection} auto-disabled after {auth_failure_count} failures: {reason}"
    )


@receiver(connection_status_changed, dispatch_uid="log_status_change")
def log_status_change(sender, connection, is_connected, previous_connected, **kwargs):
    if is_connected and not previous_connected:
        log.info("Connection %s recovered", connection)
```

### Post-sync processing

```python
from django.dispatch import receiver
from django_bapp_connectors.signals import sync_completed


@receiver(sync_completed, dispatch_uid="process_synced_orders")
def on_sync_completed(sender, connection, sync_result, resource_type, **kwargs):
    if resource_type == "orders" and sync_result.items_fetched > 0:
        notify_user(f"Synced {sync_result.items_fetched} new orders from {connection}")
```

### Signal reference

| Signal | When | Key kwargs |
|--------|------|------------|
| `webhook_event_received` | Webhook persisted, before async processing | `webhook_event`, `connection`, `provider_family`, `provider_name` |
| `webhook_event_processed` | Webhook parsed by adapter | `webhook_event`, `webhook_dto`, `connection`, `event_type`, `provider_family`, `provider_name` |
| `connection_status_changed` | `is_connected` or `is_enabled` changed | `connection`, `is_connected`, `is_enabled`, `previous_connected`, `previous_enabled` |
| `connection_disabled` | Circuit breaker threshold reached | `connection`, `auth_failure_count`, `reason` |
| `sync_completed` | Sync finished successfully | `connection`, `sync_state`, `sync_result`, `resource_type`, `is_full_resync` |

## Execution Logging

Log every HTTP call made through a connection for debugging and audit:

```python
from django_bapp_connectors.callbacks import make_execution_log_callback
from connectors.models import ExecutionLog

on_response, on_error = make_execution_log_callback(ExecutionLog, connection)

# Wire into the HTTP client middleware
adapter = connection.get_adapter()
adapter.client.http.middleware.add_on_response(on_response)
adapter.client.http.middleware.add_on_error(on_error)

# Now every API call is logged
orders = adapter.get_orders()
# -> ExecutionLog row: action="GET https://...", status=200, duration_ms=342
```

## Encryption

Credentials are encrypted at rest using [Fernet symmetric encryption](https://cryptography.io/en/latest/fernet/).

- **Default:** Derives a Fernet key from `SECRET_KEY` (sufficient for most setups)
- **Production:** Set `BAPP_CONNECTORS["ENCRYPTION_KEY"]` to a dedicated Fernet key

Generate a key:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

The `credentials` property handles encrypt/decrypt transparently:

```python
# Writing - encrypts automatically
connection.credentials = {"token": "sk-secret123"}
connection.save()

# Reading - decrypts automatically
creds = connection.credentials
print(creds["token"])  # "sk-secret123"

# The raw field stores ciphertext
print(connection.credentials_encrypted)  # "gAAAAABk..."
```

## Model Reference

### AbstractConnection

| Field | Type | Description |
|-------|------|-------------|
| `provider_family` | CharField(50) | e.g. "shop", "courier", "storage" |
| `provider_name` | CharField(50) | e.g. "woocommerce", "gomag" |
| `display_name` | CharField(200) | Human-readable label |
| `credentials_encrypted` | TextField | Fernet-encrypted JSON |
| `config` | JSONField | Provider settings, status mapping overrides |
| `is_enabled` | BooleanField | Manual enable/disable toggle |
| `is_connected` | BooleanField | Last connection test result |
| `auth_failure_count` | IntegerField | Consecutive auth failures (circuit breaker) |
| `last_auth_failure_at` | DateTimeField | Timestamp of last auth failure |
| `disabled_reason` | CharField(500) | Why the connection was auto-disabled |

**Properties:** `is_operational`, `credentials` (decrypt/encrypt)

**Methods:** `get_adapter()`, `test_connection()`, `record_auth_failure()`, `mark_connected()`, `re_enable()`

### AbstractSyncState

| Field | Type | Description |
|-------|------|-------------|
| `resource_type` | CharField(50) | e.g. "orders", "products" |
| `cursor` | CharField(500) | Pagination cursor for incremental sync |
| `last_sync_at` | DateTimeField | When last sync completed |
| `next_sync_at` | DateTimeField | Scheduled next sync |
| `status` | CharField(20) | idle / running / completed / failed |
| `error_count` | IntegerField | Consecutive sync errors |
| `last_error` | TextField | Last error message |

**Methods:** `mark_running()`, `mark_completed()`, `mark_failed()`

### AbstractExecutionLog

| Field | Type | Description |
|-------|------|-------------|
| `action` | CharField(100) | e.g. "GET https://api.example.com/orders" |
| `method` | CharField(10) | HTTP method |
| `url` | CharField(500) | Request URL |
| `request_payload` | JSONField | Request body (optional) |
| `response_status` | IntegerField | HTTP status code |
| `response_payload` | JSONField | Response body (optional) |
| `duration_ms` | IntegerField | Request duration in milliseconds |
| `error` | TextField | Error message if request failed |

### AbstractWebhookEvent

| Field | Type | Description |
|-------|------|-------------|
| `provider` | CharField(50) | Provider that sent the webhook |
| `event_type` | CharField(100) | e.g. "order.created", "product.updated" |
| `idempotency_key` | CharField(255) | Unique key for deduplication |
| `payload` | JSONField | Webhook body |
| `headers` | JSONField | Webhook headers |
| `signature_valid` | BooleanField | Whether signature verification passed |
| `status` | CharField(20) | received / processing / processed / failed / duplicate |
| `processed_at` | DateTimeField | When processing completed |
| `error` | TextField | Error message if processing failed |

**Methods:** `mark_processing()`, `mark_processed()`, `mark_failed()`, `mark_duplicate()`

## Full Example: E-commerce Order Sync

A complete example tying all pieces together:

```python
# connectors/sync.py
from connectors.models import Connection, SyncState
from django_bapp_connectors.services import SyncService


def sync_all_shop_orders():
    """Sync orders for all active shop connections."""
    connections = Connection.objects.filter(
        provider_family="shop",
        is_enabled=True,
        is_connected=True,
    )

    for connection in connections:
        sync_state, _ = SyncState.objects.get_or_create(
            connection=connection,
            resource_type="orders",
            defaults={"status": "idle"},
        )

        result = SyncService.incremental_sync(connection, sync_state, "orders")

        if result.errors:
            print(f"[{connection}] Sync failed: {result.errors}")
        else:
            print(f"[{connection}] Fetched {result.items_fetched} orders")

        # Continue paginating if more pages exist
        while result.has_more and not result.errors:
            result = SyncService.incremental_sync(connection, sync_state, "orders")
```

```python
# connectors/views.py
from django.http import JsonResponse
from connectors.models import Connection


def setup_connection(request, company_id):
    """API endpoint to create and test a new connection."""
    connection = Connection.objects.create(
        company_id=company_id,
        provider_family=request.POST["family"],
        provider_name=request.POST["provider"],
        display_name=request.POST.get("name", ""),
        config=request.POST.get("config", {}),
    )
    connection.credentials = {
        k: v for k, v in request.POST.items()
        if k.startswith("credential_")
    }
    connection.save()

    result = connection.test_connection()
    return JsonResponse({
        "id": connection.pk,
        "connected": result.success,
        "message": result.message,
    })
```

## Requirements

- Python >= 3.11
- Django >= 4.2
- bapp-connectors
- cryptography >= 41.0
- celery >= 5.0 (optional, for async tasks)

## License

MIT
