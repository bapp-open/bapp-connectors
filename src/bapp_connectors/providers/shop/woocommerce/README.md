# WooCommerce

WooCommerce store integration for orders, products, and inventory management.

- **API version:** WC REST API v3
- **Base URL:** `https://{domain}/wp-json/wc/v3/`
- **Auth:** HTTP Basic Auth (consumer key + consumer secret), or query-string auth
- **Webhooks:** Supported (HMAC-SHA256 signature via `X-WC-Webhook-Signature`)
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive | Default |
|-------|-------|----------|-----------|---------|
| `consumer_key` | Consumer Key | No | Yes | - |
| `consumer_secret` | Consumer Secret | No | Yes | - |
| `domain` | Store Domain (e.g. https://myshop.com) | Yes | No | - |
| `verify_ssl` | Verify SSL | No | No | `true` |

Either `consumer_key`/`consumer_secret` (manual setup) or OAuth flow is required.

## Settings

| Setting | Label | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `prices_include_vat` | Store Prices Include VAT | bool | `true` | Whether the WooCommerce store uses VAT-inclusive prices (WooCommerce > Settings > Tax > Prices entered with tax). |
| `vat_rate` | VAT Rate | str | `0.19` | VAT rate as a decimal (e.g., 0.19 for 19%). Used to convert between net and gross prices. |
| `use_query_auth` | Use Query Auth | bool | `false` | Use `consumer_key`/`consumer_secret` as query parameters instead of HTTP Basic Auth (set in config, not manifest). |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (paginated) | Yes |
| Get single order | Yes |
| Update order status | Yes |
| Get products (paginated) | Yes |
| Update product stock | Yes |
| Update product price | Yes |
| BulkUpdateCapability | Yes (via /products/batch) |
| ProductCreationCapability | Yes |
| ProductFullUpdateCapability | Yes |
| CategoryManagementCapability | Yes |
| AttributeManagementCapability | Yes |
| VariantManagementCapability | Yes |
| RelatedProductCapability | Yes |
| OAuthCapability | Yes |
| WebhookCapability | Yes |
| InvoiceAttachmentCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `orders` | List orders (paginated) |
| GET | `orders/{id}` | Get single order |
| PUT | `orders/{id}` | Update order (status, etc.) |
| GET | `products` | List products (paginated) |
| GET | `products/{id}` | Get single product |
| POST | `products` | Create product |
| PUT | `products/{id}` | Update product |
| DELETE | `products/{id}` | Delete product (force) |
| POST | `products/batch` | Batch update products |
| GET | `products/categories` | List categories |
| POST | `products/categories` | Create category |
| GET | `products/attributes` | List global attributes |
| GET | `products/attributes/{id}` | Get attribute |
| POST | `products/attributes` | Create attribute |
| PUT | `products/attributes/{id}` | Update attribute |
| DELETE | `products/attributes/{id}` | Delete attribute |
| GET | `products/attributes/{id}/terms` | List attribute terms |
| POST | `products/attributes/{id}/terms` | Create attribute term |
| GET | `products/{id}/variations` | List product variations |
| GET | `products/{id}/variations/{id}` | Get single variation |
| POST | `products/{id}/variations` | Create variation |
| PUT | `products/{id}/variations/{id}` | Update variation |
| DELETE | `products/{id}/variations/{id}` | Delete variation |
| GET | `webhooks` | List webhooks |
| POST | `webhooks` | Create webhook |
| DELETE | `webhooks/{id}` | Delete webhook |

## Order Status Mapping

WooCommerce uses string-based order statuses. The adapter uses `StatusMapper` for
configurable status mapping.

### Default inbound mapping (WooCommerce -> Framework)

| WooCommerce Status | Framework Status |
|---|---|
| `pending` | `PENDING` |
| `processing` | `PENDING` |
| `on-hold` | `PENDING` |
| `completed` | `DELIVERED` |
| `cancelled` | `CANCELLED` |
| `refunded` | `CANCELLED` |
| `failed` | `CANCELLED` |

### Default outbound mapping (Framework -> WooCommerce)

| Framework Status | WooCommerce Status |
|---|---|
| `PENDING` | `pending` |
| `ACCEPTED` | `processing` |
| `PROCESSING` | `processing` |
| `SHIPPED` | `completed` |
| `DELIVERED` | `completed` |
| `CANCELLED` | `cancelled` |
| `RETURNED` | `refunded` |
| `REFUNDED` | `refunded` |

### Overriding status mapping

Each connection can override the defaults via `status_map_inbound` and
`status_map_outbound` in the connection config JSON:

```json
{
  "status_map_inbound": {
    "processing": "processing",
    "wc-custom-status": "shipped"
  },
  "status_map_outbound": {
    "shipped": "wc-custom-status",
    "delivered": "completed"
  }
}
```

## Payment Method Mapping

| WooCommerce Payment Method | Framework PaymentType |
|---|---|
| `stripe` / `stripe_cc` | `ONLINE_CARD` |
| `revolut` / `revolut_cc` / `revolut_pay` | `ONLINE_CARD` |
| `cod` | `CASH_ON_DELIVERY` |
| `bacs` / `cheque` | `BANK_TRANSFER` |

Unmapped payment methods default to `OTHER`.

## OAuth

WooCommerce uses a pseudo-OAuth flow via `/wc-auth/v1/authorize`:

1. Redirect the user to `{domain}/wc-auth/v1/authorize` with `app_name`, `scope`,
   `user_id`, `return_url`, and `callback_url`.
2. The user approves in the WooCommerce admin.
3. WooCommerce POSTs `{consumer_key, consumer_secret, key_permissions}` to the
   callback URL.
4. The callback handler serializes that POST body as JSON and passes it as the
   `code` parameter to `exchange_code_for_token()`.

WooCommerce API keys do not expire -- `refresh_token()` raises
`NotImplementedError`.

## Webhooks

Webhook events: `order.created`, `order.updated`, `product.created`.

Signatures are verified using HMAC-SHA256 with the consumer secret. The signature
is sent in the `X-WC-Webhook-Signature` header.

Webhook event type mapping:

| WooCommerce Topic | Framework EventType |
|---|---|
| `order.created` | `ORDER_CREATED` |
| `order.updated` | `ORDER_UPDATED` |
| `order.deleted` | `ORDER_CANCELLED` |
| `product.created` | `PRODUCT_CREATED` |
| `product.updated` | `PRODUCT_UPDATED` |
| `product.deleted` | `PRODUCT_DELETED` |

Webhook payloads include headers: `X-WC-Webhook-Topic`, `X-WC-Webhook-Resource`,
`X-WC-Webhook-ID`, `X-WC-Webhook-Delivery-ID`.

## Bulk Update

The `BulkUpdateCapability` uses WooCommerce's native `POST /products/batch`
endpoint, which supports up to 100 items per request. The adapter automatically
chunks larger batches. Supported fields: `stock_quantity`, `regular_price`, `name`,
`status`, `sku`, plus any extra fields.

## Related Products

The `RelatedProductCapability` supports three link types:
- `related` (read-only in WooCommerce)
- `upsell` (read/write via `upsell_ids`)
- `crosssell` (read/write via `cross_sell_ids`)

Note: `related_ids` are auto-generated by WooCommerce and cannot be set manually.

## API Quirks

- **Pagination:** Uses page-based pagination with `page` and `per_page` query
  parameters (max 100 per page). List responses do not include a total count;
  `has_more` is inferred from response length.
- **Query-string auth:** For HTTP (non-HTTPS) sites, auth credentials can be sent
  as `consumer_key` / `consumer_secret` query parameters instead of HTTP Basic Auth.
  Enable via `use_query_auth: true` in the connection config.
- **Price conversion:** If `prices_include_vat` is enabled, prices are converted
  between gross (WooCommerce) and net (framework) using the configured VAT rate.
- **Variable products:** Products with attributes where `variation = true` are
  automatically set to `type: variable`. Variations are managed via the
  `/products/{id}/variations` sub-resource.
- **Order identifiers:** Orders have both `id` (internal numeric) and `number`
  (display number). The mapper uses `number` as `order_id`.
- **Force delete:** Product and variation deletes use `force=true` query parameter
  to bypass the trash.
- **Product attributes:** WooCommerce distinguishes between global attributes
  (registered via `/products/attributes`) and product-level attributes (inline on
  the product). Both are supported. Global attributes have terms
  (via `/products/attributes/{id}/terms`).
- **Images with position:** Product images include `src`, `alt`, and `position`.
  The mapper preserves all three fields.
