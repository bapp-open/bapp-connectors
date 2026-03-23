# Provider Development Guide

This guide explains how to add a new provider to `bapp-connectors`, or how to create an entirely new provider family.

## Architecture Overview

```
                 ┌─────────────────┐
                 │  Port Interface  │  (contract)
                 │  e.g. ShopPort   │
                 └────────┬────────┘
                          │ implements
                 ┌────────▼────────┐
                 │    Adapter       │  (your code)
                 │  e.g. Trendyol   │
                 └────────┬────────┘
                          │ uses
          ┌───────────────┼───────────────┐
          │               │               │
   ┌──────▼──────┐ ┌─────▼─────┐ ┌───────▼──────┐
   │   Client    │ │  Mappers  │ │   Manifest   │
   │ (raw HTTP)  │ │ (DTO ↔ API)│ │ (declaration)│
   └─────────────┘ └───────────┘ └──────────────┘
```

Every provider consists of **7 files** in a single directory:

| File | Purpose |
|------|---------|
| `manifest.py` | Declares capabilities, auth, settings, rate limits, webhooks, base URL |
| `client.py` | Raw HTTP API calls (no business logic) |
| `adapter.py` | Implements port interface(s) + capabilities |
| `mappers.py` | Converts between provider payloads and normalized DTOs |
| `models.py` | Pydantic models for provider-specific API payloads |
| `errors.py` | Maps provider errors to framework error types |
| `__init__.py` | Re-exports adapter + registers with the global registry |

---

## Adding a New Provider (Step by Step)

We'll walk through adding a fictional marketplace called "Acme Shop".

### Step 1: Create the directory

```
src/bapp_connectors/providers/shop/acme/
├── __init__.py
├── manifest.py
├── client.py
├── adapter.py
├── mappers.py
├── models.py
├── errors.py
└── tests/
    ├── __init__.py
    ├── test_adapter.py
    ├── test_mappers.py
    └── fixtures/
        └── orders_response.json
```

### Step 2: Define the manifest (`manifest.py`)

The manifest declares everything the framework needs to know about your provider.

```python
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
    WebhookConfig,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    # ── Identity ──
    name="acme",                            # unique identifier (lowercase, no spaces)
    family=ProviderFamily.SHOP,             # SHOP | COURIER | PAYMENT | MESSAGING | STORAGE
    display_name="Acme Shop",               # human-readable name
    description="Acme marketplace integration.",
    base_url="https://api.acme.com/v1/",    # API base URL

    # ── Authentication ──
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,       # NONE | BASIC | TOKEN | BEARER | API_KEY | CUSTOM
        required_fields=[
            CredentialField(name="token", label="API Token", sensitive=True),
            CredentialField(name="shop_id", label="Shop ID", sensitive=False),
            # Optional fields:
            CredentialField(name="sandbox", label="Sandbox Mode", required=False, default="false"),
        ],
    ),

    # ── Tenant Settings ──
    # Settings are tenant-configurable options (separate from auth credentials).
    # Stored in the Connection.config JSONField. Passed as `config` dict to the adapter.
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="page_size",
                label="Page Size",
                field_type=FieldType.INT,
                default=50,
                help_text="Number of items per API page.",
            ),
            SettingsField(
                name="sync_mode",
                label="Sync Mode",
                field_type=FieldType.SELECT,
                choices=["incremental", "full"],
                default="incremental",
                help_text="How to sync orders from Acme.",
            ),
            SettingsField(
                name="auto_confirm",
                label="Auto-Confirm Orders",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Automatically confirm new orders on sync.",
            ),
        ],
    ),

    # ── Capabilities ──
    # List ALL port + capability interfaces your adapter implements.
    # The registry validates this on registration.
    capabilities=[ShopPort],

    # ── Rate Limiting ──
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),

    # ── Retry Policy ──
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        base_delay=1.0,
        max_delay=60.0,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),

    # ── Webhooks (optional) ──
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha256",         # or "hmac-sha1" or None
        signature_header="X-Acme-Signature",    # header containing the signature
        events=["order.created", "order.updated", "product.updated"],
    ),
)
```

**Auth strategies explained:**

| Strategy | How the framework applies it |
|----------|-----|
| `NONE` | No auth headers added |
| `BASIC` | HTTP Basic Auth using `credentials["username"]` and `credentials["password"]` |
| `TOKEN` | `Authorization: {token}` header |
| `BEARER` | `Authorization: Bearer {token}` header |
| `API_KEY` | Not auto-applied; use `CUSTOM` and handle in adapter |
| `CUSTOM` | Framework passes `NoAuth`; your adapter/client manages auth itself |

**Settings field types:**

| FieldType | Python type | UI widget |
|-----------|------------|-----------|
| `STR` | `str` | Text input |
| `BOOL` | `bool` | Toggle/checkbox |
| `INT` | `int` | Number input |
| `SELECT` | `str` | Dropdown (requires `choices`) |
| `TEXTAREA` | `str` | Multi-line text area |

Settings vs credentials:
- **Credentials** (`auth.required_fields`) = authentication secrets, stored encrypted in `credentials_encrypted`
- **Settings** (`settings.fields`) = tenant preferences, stored in `config` JSONField, passed as `config` dict to adapter

The registry validates settings (required fields, choice constraints) and applies defaults before passing `config` to the adapter.

### Step 3: Create Pydantic models (`models.py`)

Model the **raw API payloads** (not DTOs). These represent what the provider's API sends/receives.

```python
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class AcmeOrder(BaseModel):
    """Raw order from Acme API."""
    id: int
    order_number: str = Field(alias="orderNumber")
    status: str = ""
    total: Decimal = Decimal("0")
    currency: str = "USD"
    items: list[dict] = []
    customer: dict = {}
    created_at: str = ""

    model_config = {"populate_by_name": True}


class AcmeProduct(BaseModel):
    """Raw product from Acme API."""
    id: int
    sku: str = ""
    name: str = ""
    price: Decimal = Decimal("0")
    stock: int = 0
    active: bool = True
```

### Step 4: Build the HTTP client (`client.py`)

The client handles **raw HTTP calls only**. No DTO mapping, no business logic.

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class AcmeApiClient:
    """Low-level Acme API client."""

    def __init__(self, http_client: ResilientHttpClient, shop_id: str):
        self.http = http_client
        self.shop_id = shop_id

    def test_auth(self) -> bool:
        try:
            self.http.get("shop/info")
            return True
        except Exception:
            return False

    def get_orders(self, page: int = 1, **kwargs) -> dict:
        return self.http.get("orders", params={"page": page, "shop_id": self.shop_id}, **kwargs)

    def get_order(self, order_id: str) -> dict:
        return self.http.get(f"orders/{order_id}")

    def get_products(self, page: int = 1, **kwargs) -> dict:
        return self.http.get("products", params={"page": page}, **kwargs)

    def update_product(self, product_id: str, data: dict, **kwargs) -> dict:
        return self.http.put(f"products/{product_id}", json=data, **kwargs)
```

### Step 5: Write the mappers (`mappers.py`)

Mappers convert between **provider-specific payloads** and **framework DTOs**. This is the normalization boundary.

```python
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    Product,
    ProviderMeta,
)

# Map provider statuses to normalized statuses
ACME_STATUS_MAP: dict[str, OrderStatus] = {
    "new": OrderStatus.PENDING,
    "processing": OrderStatus.PROCESSING,
    "shipped": OrderStatus.SHIPPED,
    "delivered": OrderStatus.DELIVERED,
    "cancelled": OrderStatus.CANCELLED,
}


def order_from_acme(data: dict) -> Order:
    """Map an Acme order response to a normalized Order DTO."""
    items = [
        OrderItem(
            product_id=str(item["product_id"]),
            sku=item.get("sku", ""),
            name=item.get("name", ""),
            quantity=Decimal(str(item.get("quantity", 1))),
            unit_price=Decimal(str(item.get("price", 0))),
        )
        for item in data.get("items", [])
    ]

    return Order(
        order_id=str(data.get("orderNumber", data.get("id", ""))),
        status=ACME_STATUS_MAP.get(data.get("status", ""), OrderStatus.PENDING),
        currency=data.get("currency", "USD"),
        items=items,
        total=Decimal(str(data.get("total", 0))),
        provider_meta=ProviderMeta(
            provider="acme",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


def orders_from_acme(response: dict) -> PaginatedResult[Order]:
    """Map a paginated response to PaginatedResult[Order]."""
    orders = [order_from_acme(o) for o in response.get("data", [])]
    page = response.get("page", 1)
    total_pages = response.get("total_pages", 1)
    return PaginatedResult(
        items=orders,
        cursor=str(page + 1) if page < total_pages else None,
        has_more=page < total_pages,
        total=response.get("total"),
    )
```

**Rules for mappers:**
- Always set `provider_meta` with raw payload for debugging
- Map provider statuses to framework enums
- Put provider-specific fields in `extra: dict`
- Keep normalized fields (IDs, amounts, dates) in their proper DTO fields

### Step 6: Map errors (`errors.py`)

```python
from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class AcmeError(ProviderError):
    """Base Acme error."""
    pass


class AcmeAPIError(AcmeError):
    """Acme returned an API error."""
    pass


def classify_acme_error(status_code: int, body: str = "") -> None:
    """Map an Acme HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"Acme auth failed: {body[:200]}")
    if status_code == 429:
        raise RateLimitError("Acme rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Acme client error {status_code}: {body[:500]}", status_code=status_code)
    raise AcmeAPIError(f"Acme server error {status_code}: {body[:500]}", status_code=status_code)
```

### Step 7: Build the adapter (`adapter.py`)

The adapter **implements the port interface** and wires everything together.

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import ConnectionTestResult, Order, PaginatedResult, Product
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.acme.client import AcmeApiClient
from bapp_connectors.providers.shop.acme.manifest import manifest
from bapp_connectors.providers.shop.acme.mappers import order_from_acme, orders_from_acme

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class AcmeShopAdapter(ShopPort):
    """Acme marketplace adapter implementing ShopPort."""

    manifest = manifest  # REQUIRED: attach the manifest to the class

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self.shop_id = credentials.get("shop_id", "")
        self._page_size = config.get("page_size", 50)
        self._auto_confirm = config.get("auto_confirm", False)

        # If no http_client provided (standalone use), create one
        if http_client is None:
            from bapp_connectors.core.http import BearerAuth
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="acme",
            )

        self.client = AcmeApiClient(http_client=http_client, shop_id=self.shop_id)

    # ── BasePort (required) ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="OK" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── ShopPort (required) ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        page = int(cursor) if cursor else 1
        response = self.client.get_orders(page=page)
        return orders_from_acme(response)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(order_id)
        return order_from_acme(data)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        # ... implement similarly
        pass

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.update_product(product_id, {"stock": quantity})

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        self.client.update_product(product_id, {"price": str(price)})
```

**Key requirements:**
- `manifest = manifest` class attribute is **mandatory** (registry reads it)
- `__init__` must accept `credentials: dict`, `http_client: ResilientHttpClient | None`, and `config: dict | None = None`
- Access tenant settings via `config.get("setting_name", default)` — defaults are pre-applied by the registry
- Implement ALL abstract methods from the port
- Implement ALL declared capabilities from the manifest

### Step 8: Register the adapter (`__init__.py`)

```python
"""Acme marketplace provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.acme.adapter import AcmeShopAdapter
from bapp_connectors.providers.shop.acme.manifest import manifest

__all__ = ["AcmeShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(AcmeShopAdapter)
```

### Step 9: Write tests

```python
# tests/test_adapter.py
import responses
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.acme import AcmeShopAdapter

def test_implements_port():
    adapter = AcmeShopAdapter(credentials={"token": "test", "shop_id": "1"})
    assert isinstance(adapter, ShopPort)

@responses.activate
def test_get_orders():
    responses.add(responses.GET, "https://api.acme.com/v1/orders", json={"data": [], "page": 1, "total_pages": 1})
    adapter = AcmeShopAdapter(credentials={"token": "test", "shop_id": "1"})
    result = adapter.get_orders()
    assert result.items == []
```

### Step 10: Verify

```bash
# Import test
uv run python -c "from bapp_connectors.providers.shop.acme import AcmeShopAdapter; print('OK')"

# Registry test
uv run python -c "
from bapp_connectors.providers.shop.acme import AcmeShopAdapter
from bapp_connectors.core.registry import registry
print(registry.is_registered('shop', 'acme'))  # True
"

# Run tests
uv run pytest src/bapp_connectors/providers/shop/acme/tests/ -v

# Lint
uv run ruff check src/bapp_connectors/providers/shop/acme/
```

---

## Adding Optional Capabilities

To add capabilities beyond the base port, inherit from the capability interface:

```python
from bapp_connectors.core.capabilities import BulkUpdateCapability, WebhookCapability

class AcmeShopAdapter(ShopPort, BulkUpdateCapability, WebhookCapability):
    manifest = manifest  # must list all capabilities

    # ShopPort methods...

    # BulkUpdateCapability
    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        ...

    # WebhookCapability
    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        ...

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        ...
```

And declare them in the manifest:

```python
capabilities=[ShopPort, BulkUpdateCapability, WebhookCapability],
```

The registry will **reject registration** if you declare a capability but don't implement it.

### Available capabilities

| Capability | Methods |
|---|---|
| `BulkUpdateCapability` | `bulk_update_products(updates) -> BulkResult` |
| `BulkImportCapability` | `bulk_import_products(products) -> BulkResult` |
| `WebhookCapability` | `verify_webhook(headers, body, secret) -> bool`, `parse_webhook(headers, body) -> WebhookEvent` |
| `OAuthCapability` | `get_authorize_url(redirect_uri, state) -> str`, `exchange_code_for_token(code, ...) -> OAuthTokens`, `refresh_token(refresh_token) -> OAuthTokens` |
| `InvoiceAttachmentCapability` | `attach_invoice(order_id, invoice_url) -> bool` |
| `ProductFeedCapability` | `generate_feed(products, format) -> str \| bytes` |
| `EmbeddingCapability` | `embed(texts, model) -> EmbeddingResult` |
| `TranscriptionCapability` | `transcribe(audio, model, language) -> TranscriptionResult` |
| `StreamingCapability` | `stream(messages, model) -> Iterator[LLMChunk]` |
| `ImageGenerationCapability` | `generate_image(prompt, model, size) -> ImageResult` |

---

## Creating a New Provider Family

If the existing families (shop, courier, payment, messaging, storage, llm) don't fit, you can create a new one.

### Step 1: Add the family to the enum

Edit `src/bapp_connectors/core/types.py`:

```python
class ProviderFamily(StrEnum):
    SHOP = "shop"
    COURIER = "courier"
    PAYMENT = "payment"
    MESSAGING = "messaging"
    STORAGE = "storage"
    LLM = "llm"
    ACCOUNTING = "accounting"   # <-- new family
```

### Step 2: Create the port interface

Create `src/bapp_connectors/core/ports/accounting.py`:

```python
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import PaginatedResult


class AccountingPort(BasePort):
    """Contract for accounting/ERP integrations."""

    @abstractmethod
    def get_invoices(self, since=None, cursor=None) -> PaginatedResult:
        ...

    @abstractmethod
    def create_invoice(self, data: dict) -> dict:
        ...

    @abstractmethod
    def get_chart_of_accounts(self) -> list[dict]:
        ...
```

**Port design rules:**
- Define the **smallest realistic contract** that all providers of this type must support
- Use framework DTOs for return types where possible
- Provider-specific features go in optional capabilities, not the port
- Every method that returns a list should use `PaginatedResult[T]`

### Step 3: Export from ports `__init__.py`

Add to `src/bapp_connectors/core/ports/__init__.py`:

```python
from .accounting import AccountingPort
```

### Step 4: (Optional) Create family-specific DTOs

If your family needs new normalized data types, add them to `src/bapp_connectors/core/dto/`:

```python
# src/bapp_connectors/core/dto/invoice.py
class Invoice(BaseDTO):
    invoice_id: str
    number: str
    amount: Decimal
    currency: str
    ...
```

### Step 5: Create providers

Create providers under `src/bapp_connectors/providers/accounting/`:

```
providers/accounting/
├── __init__.py
├── xero/
│   ├── __init__.py
│   ├── manifest.py
│   ├── client.py
│   ├── adapter.py    # implements AccountingPort
│   ├── mappers.py
│   ├── models.py
│   └── errors.py
└── quickbooks/
    └── ...
```

---

## Provider Checklist

Before submitting a new provider, verify:

- [ ] `manifest.py` — All fields populated, `base_url` set, capabilities declared, settings defined
- [ ] `client.py` — Raw HTTP only, uses `ResilientHttpClient`, no Django imports
- [ ] `adapter.py` — `manifest = manifest` class attribute, `__init__` accepts `config`, implements ALL port methods + declared capabilities
- [ ] `mappers.py` — Sets `provider_meta` on DTOs, maps statuses to framework enums, provider-specific data in `extra`
- [ ] `models.py` — Pydantic models for raw API payloads, `datetime`/`Decimal` imported at module level
- [ ] `errors.py` — Maps HTTP errors to framework error hierarchy
- [ ] `__init__.py` — Calls `registry.register(YourAdapter)`
- [ ] Tests — At minimum: port compliance, mapper roundtrips, adapter with mocked HTTP
- [ ] `uv run ruff check` passes
- [ ] `uv run pytest` passes
- [ ] No Django imports anywhere in the provider code
