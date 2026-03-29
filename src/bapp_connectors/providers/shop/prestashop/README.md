# PrestaShop

PrestaShop webservice integration for orders, products, categories, and inventory management.

- **API version:** Webservice REST API
- **Base URL:** `https://{domain}/api/`
- **Auth:** HTTP Basic Auth (API key as username, empty password) or query-string auth (`ws_key`)
- **Webhooks:** Supported (no signature verification)
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `domain` | Shop Domain (e.g. https://myshop.com) | Yes | No |
| `token` | API Key | Yes | Yes |

## Settings

| Setting | Label | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `prices_include_vat` | Store Prices Include VAT | bool | `true` | Whether PrestaShop prices include tax (tax_incl fields). |
| `vat_rate` | VAT Rate | str | `0.19` | VAT rate as decimal (e.g., 0.19 for 19%). |
| `use_query_auth` | Use Query Auth | bool | `false` | Use `ws_key` query parameter instead of HTTP Basic Auth (set in config, not manifest). |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders | Yes |
| Get single order | Yes |
| Update order status | Yes (via order_histories) |
| Get products (paginated) | Yes |
| Update product stock | Yes |
| Update product price | Yes |
| BulkUpdateCapability | Yes |
| ProductCreationCapability | Yes |
| ProductFullUpdateCapability | Yes |
| CategoryManagementCapability | Yes |
| AttributeManagementCapability | Yes |
| VariantManagementCapability | Yes |
| WebhookCapability | Yes |
| OAuthCapability | No |
| InvoiceAttachmentCapability | No |
| RelatedProductCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `products` | List products |
| GET | `products/{id}` | Get single product |
| POST | `products` | Create product |
| PUT | `products/{id}` | Update product |
| DELETE | `products/{id}` | Delete product |
| GET | `orders` | List orders |
| GET | `orders/{id}` | Get single order |
| PUT | `orders/{id}` | Update order |
| POST | `order_histories` | Create order history entry (change status) |
| GET | `customers/{id}` | Get customer |
| GET | `addresses/{id}` | Get address |
| GET | `countries/{id}` | Get country (for ISO code) |
| GET | `states/{id}` | Get state/region |
| GET | `categories` | List categories |
| POST | `categories` | Create category |
| GET | `stock_availables` | Get stock availability |
| PUT | `stock_availables` | Update stock |
| GET | `product_features` | List product features (attributes) |
| GET | `product_features/{id}` | Get product feature |
| POST | `product_features` | Create product feature |
| GET | `product_feature_values` | List feature values |
| POST | `product_feature_values` | Create feature value |
| GET | `product_options` | List product options (variant attributes) |
| GET | `product_option_values` | List option values |
| POST | `product_options` | Create product option |
| POST | `product_option_values` | Create option value |
| GET | `combinations` | List combinations (variants) |
| GET | `combinations/{id}` | Get single combination |
| POST | `combinations` | Create combination |
| PUT | `combinations/{id}` | Update combination |
| DELETE | `combinations/{id}` | Delete combination |
| GET | `images/products` | List product images |

## Order Status Mapping

PrestaShop uses numeric order state IDs. The defaults below are common across
installations but can vary. The adapter uses `StatusMapper` for configurable
status mapping.

### Default inbound mapping (PrestaShop -> Framework)

| PS State ID | Meaning | Framework Status |
|---|---|---|
| `1` | Awaiting check payment | `PENDING` |
| `2` | Payment accepted | `ACCEPTED` |
| `3` | Processing in progress | `PROCESSING` |
| `4` | Shipped | `SHIPPED` |
| `5` | Delivered | `DELIVERED` |
| `6` | Cancelled | `CANCELLED` |
| `7` | Refunded | `REFUNDED` |
| `8` | Payment error | `CANCELLED` |
| `9` | On backorder (not paid) | `PENDING` |
| `10` | Awaiting bank wire | `PENDING` |
| `11` | Remote payment accepted | `PROCESSING` |
| `12` | On backorder (paid) | `PROCESSING` |

### Default outbound mapping (Framework -> PrestaShop)

| Framework Status | PS State ID |
|---|---|
| `PENDING` | `1` |
| `ACCEPTED` | `2` |
| `PROCESSING` | `3` |
| `SHIPPED` | `4` |
| `DELIVERED` | `5` |
| `CANCELLED` | `6` |
| `REFUNDED` | `7` |
| `RETURNED` | `7` |

### Overriding status mapping

Each connection can override the defaults via `status_map_inbound` and
`status_map_outbound` in the connection config JSON:

```json
{
  "status_map_inbound": {
    "13": "processing"
  },
  "status_map_outbound": {
    "shipped": "14"
  }
}
```

## Payment Method Mapping

| PrestaShop Module | Framework PaymentType |
|---|---|
| `euplatesc` | `ONLINE_CARD` |
| `ps_wirepayment` | `PAYMENT_ORDER` |
| `ps_cashondelivery` | `CASH_ON_DELIVERY` |
| `cargus` | `CASH_ON_DELIVERY` |
| `ramburs` | `CASH_ON_DELIVERY` |
| `ps_checkpayment` | `PAYMENT_ORDER` |

Unmapped payment methods default to `OTHER`.

## Required API Permissions

The connection test verifies the following API permissions are granted to the key:

- `addresses`, `countries`, `customers`, `orders`, `products`, `categories`,
  `taxes`, `images`

## Webhooks

PrestaShop webhooks are supported but do not use signature verification. The
`verify_webhook()` method returns `true` if the body is valid JSON.

Supported events: `order.created`, `order.update`, `order.return`.

Webhook payloads contain `id_order` or `id_product` to identify the resource.

## API Quirks

- **XML for writes:** PrestaShop only accepts XML for POST/PUT operations. The
  client automatically converts JSON payloads to XML using `_dict_to_xml()`.
  Reads return JSON (via `Output-Format: JSON` header).
- **Multilingual fields:** Names, descriptions, and other text fields use a
  `{language: [{attrs: {id}, value}]}` format. The `_multilang()` helper wraps
  strings in this format (default language ID = 1).
- **Order enrichment:** Fetching a complete order requires multiple API calls:
  order details, delivery address, invoice address, customer, country ISO code,
  and state name. The adapter's `_enrich_order()` method handles this.
- **Nested response format:** List responses can be nested as
  `{"orders": {"order": [...]}}` (header auth) or flat as `{"orders": [...]}`
  (query auth). The `_unwrap_list()` helper handles both formats.
- **Combination prices are deltas:** PrestaShop variant (combination) prices are
  price *impacts* (deltas from the base product price), not absolute prices.
  The `extra.price_is_delta = True` flag is set on mapped variants.
- **Features vs Options:** PrestaShop has two types of attributes: "product
  features" (informational, e.g., material) and "product options" (variant
  attributes, e.g., size, color). Both are mapped to `AttributeDefinition` with
  `extra.kind = "feature"` or `"option"`.
- **Price conversion:** If `prices_include_vat` is enabled, prices are converted
  between gross (PrestaShop) and net (framework) using the configured VAT rate.
- **Shipping as line item:** Shipping cost is added as a separate `OrderItem` with
  `item_id = "shipping"` and `extra.is_transport = True`.
