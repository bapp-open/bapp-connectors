# Django Integration Guide

`django-bapp-connectors` provides multi-tenant connection management, sync state tracking, webhook persistence, execution logging, and a circuit breaker for the `bapp-connectors` framework.

## Installation

```bash
# From the monorepo
uv pip install -e packages/django

# Or via pip
pip install django-bapp-connectors
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "django_bapp_connectors",
    "myapp",  # your app that defines concrete models
]
```

## Quick Start

### 1. Define your concrete models

The package provides **abstract models**. You subclass them and add your tenant FK:

```python
# myapp/models.py
from django.db import models
from django_bapp_connectors.models import (
    AbstractConnection,
    AbstractExecutionLog,
    AbstractSyncState,
    AbstractWebhookEvent,
)


class Connection(AbstractConnection):
    """A connector connection scoped to a company."""
    company = models.ForeignKey("company.Company", on_delete=models.CASCADE, related_name="connections")

    class Meta:
        unique_together = ["company", "provider_family", "provider_name"]


class SyncState(AbstractSyncState):
    """Tracks sync cursor per connection + resource type."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="sync_states")

    class Meta:
        unique_together = ["connection", "resource_type"]


class WebhookEvent(AbstractWebhookEvent):
    """Persisted webhook events for audit and dedup."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, null=True, related_name="webhook_events")


class ExecutionLog(AbstractExecutionLog):
    """Audit log for every adapter API call."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="execution_logs")
```

Then run migrations:

```bash
python manage.py makemigrations myapp
python manage.py migrate
```

### 2. Register admin

```python
# myapp/admin.py
from django.contrib import admin
from django_bapp_connectors.admin import (
    ConnectionAdminMixin,
    ExecutionLogAdminMixin,
    SyncStateAdminMixin,
    WebhookEventAdminMixin,
)
from myapp.models import Connection, ExecutionLog, SyncState, WebhookEvent


@admin.register(Connection)
class ConnectionAdmin(ConnectionAdminMixin, admin.ModelAdmin):
    list_display = ["company", *ConnectionAdminMixin.list_display]
    list_filter = ["company", *ConnectionAdminMixin.list_filter]


@admin.register(SyncState)
class SyncStateAdmin(SyncStateAdminMixin, admin.ModelAdmin):
    pass


@admin.register(WebhookEvent)
class WebhookEventAdmin(WebhookEventAdminMixin, admin.ModelAdmin):
    pass


@admin.register(ExecutionLog)
class ExecutionLogAdmin(ExecutionLogAdminMixin, admin.ModelAdmin):
    pass
```

### 3. Configure settings (optional)

```python
# settings.py
BAPP_CONNECTORS = {
    # Fernet key for credential encryption. If empty, derives from SECRET_KEY.
    "ENCRYPTION_KEY": "",

    # Base URL for webhook endpoints
    "WEBHOOK_BASE_URL": "https://yourdomain.com/webhooks/",
}
```

---

## Creating Connections

```python
from myapp.models import Connection

# Import the provider to register it
from bapp_connectors.providers.shop.trendyol import TrendyolShopAdapter

# Create a connection
conn = Connection.objects.create(
    company=company,
    provider_family="shop",
    provider_name="trendyol",
    display_name="My Trendyol Store",
    config={"item_match_field": "barcode"},  # tenant settings — validated & passed to adapter
)

# Set credentials (encrypted automatically)
conn.credentials = {
    "username": "api_user",
    "password": "api_pass",
    "seller_id": "12345",
    "country": "RO",
}
conn.save()

# Test the connection
result = conn.test_connection()
print(result.success)   # True/False
print(result.message)   # "Connection successful" or error details
print(conn.is_connected)  # Updated automatically
```

---

## Using Adapters

### Direct usage

```python
# Get the adapter from a connection
adapter = conn.get_adapter()

# Use the port interface
orders = adapter.get_orders(since=some_datetime)
for order in orders.items:
    print(order.order_id, order.status, order.total)

# Check capabilities
from bapp_connectors.core.capabilities import BulkUpdateCapability
if adapter.supports(BulkUpdateCapability):
    result = adapter.bulk_update_products(updates)
```

### LLM usage

```python
from bapp_connectors.core.dto import ChatMessage, ChatRole

# Get adapter from a connection configured for LLM
adapter = llm_conn.get_adapter()

# Chat completion
response = adapter.complete([
    ChatMessage(role=ChatRole.SYSTEM, content="You are a helpful assistant."),
    ChatMessage(role=ChatRole.USER, content="Summarize this invoice."),
])
print(response.content)
print(f"Tokens: {response.usage.total_tokens}")

# Embeddings (if supported)
from bapp_connectors.core.capabilities import EmbeddingCapability
if adapter.supports(EmbeddingCapability):
    result = adapter.embed(["search query", "document text"])
    print(f"Dimensions: {len(result.embeddings[0])}")

# Audio transcription (OpenAI Whisper)
from bapp_connectors.core.capabilities import TranscriptionCapability
if adapter.supports(TranscriptionCapability):
    with open("meeting.mp3", "rb") as f:
        result = adapter.transcribe(f.read(), language="ro")
    print(result.text)

# Tool/function calling
from bapp_connectors.core.dto import ToolDefinition
response = adapter.complete(
    messages=[ChatMessage(role=ChatRole.USER, content="What's the weather in Bucharest?")],
    tools=[ToolDefinition(name="get_weather", description="Get weather", parameters={"type": "object", "properties": {"city": {"type": "string"}}})],
)
if response.tool_calls:
    print(response.tool_calls[0].name, response.tool_calls[0].arguments)

# Platform-level key: tenant has no api_key, platform provides it via config
# conn.credentials = {}  (empty)
# conn.config = {"platform_api_key": "sk-platform-key", "default_model": "gpt-4o-mini"}
adapter = conn.get_adapter()  # uses platform key automatically
```

### Via the service layer

```python
from django_bapp_connectors.services import ConnectionService

# Get adapter
adapter = ConnectionService.get_adapter(conn)

# Test connection
result = ConnectionService.test_connection(conn)

# Rotate credentials
ConnectionService.rotate_credentials(conn, new_credentials={"token": "new_token"})

# Update tenant settings (validated against manifest)
ConnectionService.update_settings(conn, {"page_size": 100, "sync_mode": "full"})

# Validate settings without saving
errors = ConnectionService.validate_settings(conn, {"sync_mode": "invalid"})
# errors = ["Invalid value for sync_mode: 'invalid'. Must be one of: ['incremental', 'full']"]

# List available providers
manifests = ConnectionService.list_available_providers(family="shop")
for m in manifests:
    print(f"{m.name}: {m.display_name} (auth: {m.auth.strategy})")
    for field in m.auth.required_fields:
        print(f"  - {field.name}: {field.label} (required={field.required})")
    for field in m.settings.fields:
        print(f"  - [setting] {field.name}: {field.label} (type={field.field_type}, default={field.default})")
```

---

## Sync Operations

### Incremental sync (cursor-based)

```python
from django_bapp_connectors.services import SyncService
from myapp.models import SyncState

# Get or create sync state
sync_state, _ = SyncState.objects.get_or_create(
    connection=conn,
    resource_type="orders",
    defaults={"status": "idle"},
)

# Run incremental sync (resumes from last cursor)
result = SyncService.incremental_sync(conn, sync_state, "orders")
print(result.items_fetched)
print(result.cursor)       # cursor for next page
print(result.has_more)     # True if more pages available

# Full resync (resets cursor, starts from beginning)
result = SyncService.full_resync(conn, sync_state, "orders")
```

### Async via Celery

```python
from django_bapp_connectors.tasks import incremental_sync, execute_adapter_method

# Async incremental sync
incremental_sync.delay(
    connection_id=conn.pk,
    resource_type="orders",
    app_label="myapp",
    model_name="Connection",
    sync_state_app="myapp",
    sync_state_model="SyncState",
)

# Async method call on adapter
execute_adapter_method.delay(
    connection_id=conn.pk,
    method_name="get_orders",
    app_label="myapp",
    model_name="Connection",
    since="2024-01-01",
)
```

---

## Circuit Breaker (Auth Failure Protection)

The `AbstractConnection` model includes a circuit breaker that **auto-disables connections** after repeated authentication failures, preventing cron loops.

### How it works

1. Each auth failure increments `auth_failure_count`
2. After **3 consecutive failures** (`AUTH_FAILURE_THRESHOLD`), the connection is auto-disabled:
   - `is_enabled = False`
   - `is_connected = False`
   - `disabled_reason` is set with details
3. All Celery tasks check `connection.is_operational` before running
4. Recovery requires manual intervention

### Fields

| Field | Type | Description |
|---|---|---|
| `is_enabled` | `bool` | User-controlled on/off switch |
| `is_connected` | `bool` | Last known auth status |
| `is_operational` | `property` | `is_enabled AND is_connected` — use this in cron checks |
| `auth_failure_count` | `int` | Consecutive auth failures |
| `last_auth_failure_at` | `datetime` | Timestamp of last failure |
| `disabled_reason` | `str` | Why the connection was disabled |

### Usage in cron tasks

```python
# Your periodic task:
from myapp.models import Connection

# Only process operational connections
connections = Connection.objects.filter(is_enabled=True, is_connected=True)
for conn in connections:
    execute_adapter_method.delay(
        connection_id=conn.pk,
        method_name="check_for_new_orders",
        app_label="myapp",
        model_name="Connection",
    )
```

The task itself handles auth failures automatically — if the API returns 401/403, the task calls `connection.record_auth_failure()` and the circuit breaker engages after 3 failures.

### Manual recovery

```python
# After fixing credentials in admin:
conn.credentials = {"token": "new_valid_token"}
conn.save()

# Re-enable and test
conn.re_enable()
result = conn.test_connection()
if result.success:
    print("Connection restored!")
```

### Recording auth failures manually

If you have custom code outside the Celery tasks:

```python
from bapp_connectors.core.errors import AuthenticationError

try:
    adapter = conn.get_adapter()
    adapter.get_orders()
except AuthenticationError as e:
    conn.record_auth_failure(str(e))
```

---

## Webhooks

### Setup URL routing

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    path("webhooks/", include("django_bapp_connectors.webhooks.urls")),
]
```

This creates:
- `POST /webhooks/<connection_id>/<action>/` — webhook receiver
- `GET /webhooks/oauth/callback/<provider>/` — OAuth callback

### Processing webhooks

```python
from django_bapp_connectors.services import WebhookService
from myapp.models import WebhookEvent

# Initialize the webhook service with your model
webhook_service = WebhookService(webhook_event_model=WebhookEvent)

# Process an incoming webhook (typically in a view)
event = webhook_service.receive(
    provider="trendyol",
    headers=dict(request.headers),
    body=request.body,
    signature_method="hmac-sha256",
    signature_header="X-Signature",
    secret="webhook_secret",
    connection=conn,  # optional: link to connection
)

# The event is persisted as a WebhookEvent instance
print(event.status)          # "received"
print(event.idempotency_key) # deterministic key for dedup
```

### Async webhook processing

```python
from django_bapp_connectors.tasks import process_webhook

# After persisting the event, dispatch for async processing
process_webhook.delay(
    webhook_event_id=event.pk,
    app_label="myapp",
    model_name="WebhookEvent",
)
```

---

## Execution Logging

Track every API call for audit/debugging:

```python
from django_bapp_connectors.callbacks import make_execution_log_callback
from bapp_connectors.core.http import MiddlewareChain, ResilientHttpClient

# Create middleware with logging callbacks
middleware = MiddlewareChain()
on_response, on_error = make_execution_log_callback(ExecutionLog, conn)
middleware.add_on_response(on_response)
middleware.add_on_error(on_error)

# Use when creating an HTTP client manually
client = ResilientHttpClient(
    base_url="https://api.example.com/",
    auth=auth,
    middleware=middleware,
)
```

Every HTTP call made through this client will be logged to the `ExecutionLog` model with:
- Method, URL, response status, duration
- Error details (if failed)
- Linked to the connection for filtering

---

## Credential Encryption

Credentials are encrypted at rest using Fernet symmetric encryption.

```python
# Credentials are encrypted automatically via the property setter
conn.credentials = {"token": "secret_value"}
conn.save()

# The raw database field is encrypted
print(conn.credentials_encrypted)  # "gAAAAABh..."

# Reading decrypts automatically
print(conn.credentials)  # {"token": "secret_value"}
```

### Custom encryption key

By default, the encryption key is derived from Django's `SECRET_KEY`. To use a custom key:

```python
# settings.py
from cryptography.fernet import Fernet

BAPP_CONNECTORS = {
    "ENCRYPTION_KEY": Fernet.generate_key().decode(),
}
```

---

## Available Abstract Models

### `AbstractConnection`

| Field | Type | Description |
|---|---|---|
| `provider_family` | `CharField` | Family: shop, courier, payment, messaging, storage |
| `provider_name` | `CharField` | Provider name: trendyol, sameday, stripe, etc. |
| `display_name` | `CharField` | Human-readable label |
| `credentials_encrypted` | `TextField` | Fernet-encrypted JSON credentials |
| `config` | `JSONField` | Tenant settings (declared in manifest, passed as `config` to adapter) |
| `is_enabled` | `BooleanField` | User-controlled on/off |
| `is_connected` | `BooleanField` | Last known auth status |
| `auth_failure_count` | `IntegerField` | Consecutive auth failures |
| `last_auth_failure_at` | `DateTimeField` | Last failure timestamp |
| `disabled_reason` | `CharField` | Why auto-disabled |

**Key methods:** `get_adapter()`, `test_connection()`, `record_auth_failure()`, `mark_connected()`, `re_enable()`

### `AbstractSyncState`

| Field | Type | Description |
|---|---|---|
| `resource_type` | `CharField` | "orders", "products", etc. |
| `cursor` | `CharField` | Opaque cursor from provider |
| `last_sync_at` | `DateTimeField` | Last successful sync |
| `status` | `CharField` | idle, running, completed, failed |
| `error_count` | `IntegerField` | Consecutive errors |
| `last_error` | `TextField` | Last error message |

**Key methods:** `mark_running()`, `mark_completed(cursor)`, `mark_failed(error)`

### `AbstractWebhookEvent`

| Field | Type | Description |
|---|---|---|
| `provider` | `CharField` | Provider name |
| `event_type` | `CharField` | Normalized event type |
| `idempotency_key` | `CharField` | Unique key for dedup |
| `payload` | `JSONField` | Raw webhook payload |
| `headers` | `JSONField` | Request headers |
| `signature_valid` | `BooleanField` | Signature verification result |
| `status` | `CharField` | received, processing, processed, failed, duplicate |

**Key methods:** `mark_processing()`, `mark_processed()`, `mark_failed(error)`, `mark_duplicate()`

### `AbstractExecutionLog`

| Field | Type | Description |
|---|---|---|
| `action` | `CharField` | e.g., "GET https://api.example.com/orders" |
| `method` | `CharField` | HTTP method |
| `url` | `CharField` | Request URL |
| `request_payload` | `JSONField` | Request body (optional) |
| `response_status` | `IntegerField` | HTTP status code |
| `duration_ms` | `IntegerField` | Request duration |
| `error` | `TextField` | Error message if failed |
