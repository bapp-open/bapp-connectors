# bapp-connectors

A ports-and-adapters integration framework for connecting to external services: marketplaces, couriers, payment gateways, messaging providers, and file storage.

## Architecture

```
┌──────────────────────────────────────────────┐
│  Django Layer (django-bapp-connectors)        │
│  Models, Services, Tasks, Circuit Breaker     │
├──────────────────────────────────────────────┤
│  Core Framework (bapp-connectors)             │
│  Ports, DTOs, HTTP Client, Registry, Webhooks │
├──────────────────────────────────────────────┤
│  Provider Adapters                            │
│  Trendyol, eMAG, Sameday, Stripe, ...        │
└──────────────────────────────────────────────┘
```

**Two packages, one monorepo:**

| Package | Purpose | Dependencies |
|---|---|---|
| `bapp-connectors` | Core framework + all provider adapters | `requests`, `pydantic` (no Django) |
| `django-bapp-connectors` | Multi-tenant Django integration | `django`, `bapp-connectors`, `cryptography` |

## Providers

<!-- PROVIDERS:BEGIN -->
| Family | Providers | Count |
|---|---|---|
| **Shop** | CEL.ro, eMAG, Gomag, Magento, Okazii, PrestaShop, Shopify, Trendyol, Vendigo, WooCommerce | 10 |
| **Courier** | Colete Online, GLS, Sameday | 3 |
| **Payment** | EuPlatesc, Netopia, Stripe | 3 |
| **Messaging** | GoIP, RoboSMS, SMTP Email, Telegram, WhatsApp | 5 |
| **Storage** | Dropbox, FTP File Storage, S3 Storage, SFTP, WebDAV | 5 |
| **LLM** | Anthropic, Google Gemini, Ollama, OpenAI | 4 |
| | **Total** | **30** |
<!-- PROVIDERS:END -->

## Quick Start

### Install

```bash
uv add bapp-connectors              # core only
uv add django-bapp-connectors       # with Django integration
```

### Use a provider directly

```python
from bapp_connectors.providers.shop.trendyol import TrendyolShopAdapter

adapter = TrendyolShopAdapter(credentials={
    "username": "api_user",
    "password": "api_pass",
    "seller_id": "12345",
    "country": "RO",
})

# Test connection
result = adapter.test_connection()
print(result.success)

# Fetch orders
orders = adapter.get_orders()
for order in orders.items:
    print(order.order_id, order.status, order.total)

# Check capabilities
from bapp_connectors.core.capabilities import BulkUpdateCapability
if adapter.supports(BulkUpdateCapability):
    adapter.bulk_update_products(updates)
```

### Use the registry

```python
from bapp_connectors.core.registry import registry

# Import providers to register them
import bapp_connectors.providers.shop.trendyol

# Create adapter via registry
adapter = registry.create_adapter(
    family="shop",
    provider="trendyol",
    credentials={"username": "...", "password": "...", "seller_id": "..."},
)

# List all registered providers
for manifest in registry.list_providers():
    print(f"{manifest.family}: {manifest.name}")
```

### Django integration

```python
# models.py
from django_bapp_connectors.models import AbstractConnection

class Connection(AbstractConnection):
    company = models.ForeignKey("company.Company", on_delete=models.CASCADE)

# Usage
conn = Connection.objects.create(
    company=company,
    provider_family="shop",
    provider_name="trendyol",
)
conn.credentials = {"username": "...", "password": "...", "seller_id": "..."}
conn.save()

# Get adapter and use it
adapter = conn.get_adapter()
orders = adapter.get_orders()

# Circuit breaker: auto-disables after 3 auth failures
conn.is_operational  # True when is_enabled AND is_connected
```

## Core Concepts

### Ports (Interfaces)

Each provider family has a port that defines the common contract:

- `ShopPort` — orders, products, stock/price sync
- `CourierPort` — AWB generation, tracking, shipment management
- `PaymentPort` — checkout sessions, payment status, refunds
- `MessagingPort` — send messages (SMS, email, WhatsApp, Telegram), reply to inbound
- `StoragePort` — save, open, delete, exists, listdir, size (Django Storage API compatible)
- `LLMPort` — chat completion, model listing, tool/function calling

### Capabilities (Optional Features)

Adapters can implement optional capabilities beyond their port:

- `BulkUpdateCapability` — batch product updates
- `WebhookCapability` — signature verification, webhook parsing
- `OAuthCapability` — OAuth2 flow (authorize, exchange, refresh)
- `InvoiceAttachmentCapability` — attach invoices to orders
- `ProductFeedCapability` — generate product feeds
- `EmbeddingCapability` — text embeddings for RAG/search
- `TranscriptionCapability` — audio-to-text (Whisper)
- `StreamingCapability` — streaming LLM responses
- `ImageGenerationCapability` — AI image generation

Feature discovery: `adapter.supports(BulkUpdateCapability)`

### Normalized DTOs

All providers return the same data types:

- `Order`, `OrderItem`, `OrderStatus`, `PaymentStatus`
- `Product`, `ProductUpdate`, `ProductCategory`
- `Shipment`, `AWBLabel`, `TrackingEvent`
- `CheckoutSession`, `PaymentResult`, `Refund`
- `OutboundMessage`, `InboundMessage`, `DeliveryReport`
- `ChatMessage`, `LLMResponse`, `TokenUsage`, `ModelInfo`, `ToolCall`
- `EmbeddingResult`, `TranscriptionResult`, `ImageResult`
- `Contact`, `Address`
- `PaginatedResult[T]` — cursor-based pagination

Provider-specific data lives in the `extra: dict` field and `provider_meta`.

### Resilient HTTP Client

Built-in retry, rate limiting, and observability:

- Exponential backoff with configurable max retries
- Token-bucket rate limiting per provider
- Request/response middleware chain for logging
- Error classification: retryable vs permanent

### Error Hierarchy

```
ConnectorError
├── AuthenticationError      (401/403, not retryable)
├── ConfigurationError       (bad config, not retryable)
├── ValidationError          (bad request, not retryable)
├── RateLimitError           (429, retryable, has retry_after)
├── ProviderError            (5xx, retryable)
├── PermanentProviderError   (4xx non-auth, not retryable)
├── UnsupportedFeatureError  (capability not supported)
└── WebhookVerificationError (bad signature)
```

## Development

```bash
# Setup
cd packages/connectors
uv sync --extra dev

# Run tests
uv run pytest tests/ src/bapp_connectors/providers/shop/trendyol/tests/ -v -p no:django

# Lint
uv run ruff check src/
uv run ruff format src/
```

### Django workspace

```bash
cd packages/connectors/packages/django
uv sync --extra dev
uv run pytest tests/ -v
```

## Documentation

- [Provider Development Guide](docs/PROVIDER_GUIDE.md) — How to add a new provider or create a new family
- [Django Integration Guide](docs/DJANGO_INTEGRATION.md) — How to use the Django package

## Project Structure

```
packages/connectors/
├── src/bapp_connectors/
│   ├── core/
│   │   ├── ports/          # Port interfaces (contracts)
│   │   ├── capabilities/   # Optional capability interfaces
│   │   ├── dto/            # Normalized data transfer objects
│   │   ├── http/           # Resilient HTTP client + auth + retry + rate limit
│   │   ├── webhooks/       # Webhook dispatcher + signature verification
│   │   ├── errors.py       # Error hierarchy
│   │   ├── types.py        # Enums
│   │   ├── manifest.py     # Provider manifest schema
│   │   └── registry.py     # Provider registry
│   └── providers/
<!-- STRUCTURE:BEGIN -->
│       ├── shop/          # CEL.ro, eMAG, Gomag, Magento, Okazii, PrestaShop, Shopify, Trendyol, Vendigo, WooCommerce
│       ├── courier/       # Colete Online, GLS, Sameday
│       ├── payment/       # EuPlatesc, Netopia, Stripe
│       ├── messaging/     # GoIP, RoboSMS, SMTP Email, Telegram, WhatsApp
│       ├── storage/       # Dropbox, FTP File Storage, S3 Storage, SFTP, WebDAV
│       └── llm/           # Anthropic, Google Gemini, Ollama, OpenAI
<!-- STRUCTURE:END -->
├── packages/django/        # Django integration (separate uv workspace)
│   └── src/django_bapp_connectors/
│       ├── models/         # Abstract models (Connection, SyncState, WebhookEvent, ExecutionLog)
│       ├── services/       # Service layer (Connection, Sync, Webhook)
│       ├── webhooks/       # Django views + URL routing
│       ├── tasks.py        # Celery tasks with circuit breaker
│       ├── callbacks.py    # Execution logging middleware
│       ├── encryption.py   # Fernet credential encryption
│       └── admin.py        # Admin mixins
├── tests/                  # Core framework tests
└── docs/                   # Documentation
```
