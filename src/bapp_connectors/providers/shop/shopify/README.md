# Shopify

Shopify Admin REST API integration for orders, products, variants, and inventory management.

- **API version:** 2024-01 (configurable)
- **Base URL:** `https://{store_domain}/admin/api/{api_version}/`
- **Auth:** `X-Shopify-Access-Token` header (Admin API access token or OAuth)
- **Webhooks:** Supported (HMAC-SHA256 signature via `X-Shopify-Hmac-Sha256`)
- **Rate limit:** 4 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `store_domain` | Store Domain (e.g. myshop.myshopify.com) | Yes | No |
| `access_token` | Admin API Access Token | No | Yes |
| `client_id` | App Client ID | No | No |
| `client_secret` | App Client Secret | No | Yes |

Either `access_token` (for custom/private apps) or `client_id` + `client_secret`
(for OAuth apps) is required.

## Settings

| Setting | Label | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `api_version` | API Version | str | `2024-01` | Shopify API version (e.g., 2024-01). |
| `prices_include_vat` | Prices Include VAT | bool | `false` | Whether Shopify prices include tax. |
| `vat_rate` | VAT Rate | str | `0.19` | VAT rate as decimal. |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (paginated) | Yes |
| Get single order | Yes |
| Update order status | Partial (cancel only via REST) |
| Get products (paginated) | Yes |
| Update product stock | Yes (via inventory_levels) |
| Update product price | Yes (via variant update) |
| BulkUpdateCapability | Yes |
| ProductCreationCapability | Yes |
| ProductFullUpdateCapability | Yes |
| CategoryManagementCapability | Yes (collections) |
| VariantManagementCapability | Yes |
| OAuthCapability | Yes |
| WebhookCapability | Yes |
| InvoiceAttachmentCapability | No |
| AttributeManagementCapability | No |
| RelatedProductCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `shop.json` | Connection test |
| GET | `products.json` | List products |
| GET | `products/{id}.json` | Get single product |
| POST | `products.json` | Create product |
| PUT | `products/{id}.json` | Update product |
| DELETE | `products/{id}.json` | Delete product |
| GET | `products/count.json` | Count products |
| GET | `products/{id}/variants.json` | List variants |
| GET | `variants/{id}.json` | Get single variant |
| POST | `products/{id}/variants.json` | Create variant |
| PUT | `variants/{id}.json` | Update variant |
| DELETE | `products/{id}/variants/{id}.json` | Delete variant |
| GET | `orders.json` | List orders |
| GET | `orders/{id}.json` | Get single order |
| PUT | `orders/{id}.json` | Update order |
| POST | `orders/{id}/cancel.json` | Cancel order |
| POST | `orders/{id}/close.json` | Close order |
| POST | `orders/{id}/open.json` | Reopen order |
| GET | `custom_collections.json` | List custom collections |
| POST | `custom_collections.json` | Create custom collection |
| DELETE | `custom_collections/{id}.json` | Delete collection |
| GET | `smart_collections.json` | List smart collections |
| GET | `webhooks.json` | List webhooks |
| POST | `webhooks.json` | Create webhook |
| DELETE | `webhooks/{id}.json` | Delete webhook |
| GET | `inventory_levels.json` | Get inventory levels |
| POST | `inventory_levels/set.json` | Set inventory level |

## Order Status Mapping

Shopify uses two separate status fields: `fulfillment_status` and
`financial_status`. The adapter maps `fulfillment_status` to `OrderStatus` and
`financial_status` to `PaymentStatus`. The adapter uses `StatusMapper` for
configurable status mapping.

### Default inbound mapping (Shopify fulfillment_status -> Framework)

| Shopify Fulfillment Status | Framework Status |
|---|---|
| `unfulfilled` (or null) | `PENDING` |
| `partial` | `PROCESSING` |
| `fulfilled` | `DELIVERED` |
| `restocked` | `RETURNED` |

### Financial status mapping

| Shopify Financial Status | Framework PaymentStatus |
|---|---|
| `pending` | `UNPAID` |
| `authorized` | `UNPAID` |
| `paid` | `PAID` |
| `partially_paid` | `PARTIALLY_PAID` |
| `partially_refunded` | `PAID` |
| `refunded` | `REFUNDED` |
| `voided` | `FAILED` |

### Default outbound mapping (Framework -> Shopify)

| Framework Status | Shopify Action |
|---|---|
| `DELIVERED` | `fulfilled` |
| `CANCELLED` | `cancelled` (via cancel endpoint) |

Note: Only `CANCELLED` is supported via the REST API's `cancel` endpoint. Fulfillment-based
status changes (SHIPPED, DELIVERED) require the Shopify Fulfillment API, which is
not used by the adapter.

### Overriding status mapping

Each connection can override the defaults via `status_map_inbound` and
`status_map_outbound` in the connection config JSON.

## OAuth

Shopify supports a standard OAuth 2.0 flow:

1. Redirect to `https://{store}/admin/oauth/authorize` with `client_id`, `scope`,
   `redirect_uri`, and `state`.
2. Exchange the authorization code for an access token via
   `POST https://{store}/admin/oauth/access_token`.

Scopes: `read_products`, `write_products`, `read_orders`, `write_orders`,
`read_inventory`, `write_inventory`.

Shopify offline access tokens do not expire -- `refresh_token()` raises
`NotImplementedError`.

## Webhooks

Webhook events: `orders/create`, `orders/updated`, `products/create`,
`products/update`.

Signatures are verified using HMAC-SHA256 with the webhook secret (or
`client_secret`). The signature is sent in the `X-Shopify-Hmac-Sha256` header.

Webhook event type mapping:

| Shopify Topic | Framework EventType |
|---|---|
| `orders/create` | `ORDER_CREATED` |
| `orders/updated` | `ORDER_UPDATED` |
| `orders/cancelled` | `ORDER_CANCELLED` |
| `products/create` | `PRODUCT_CREATED` |
| `products/update` | `PRODUCT_UPDATED` |
| `products/delete` | `PRODUCT_DELETED` |

## API Quirks

- **Products always have variants:** Even "simple" products have at least one
  variant. Prices and SKUs live on variants, not the product itself.
- **Max 3 options:** Shopify allows a maximum of 3 product options (e.g., size,
  color, material). Variant attributes are stored as `option1`, `option2`,
  `option3`.
- **Stock via inventory_levels:** Stock updates go through
  `inventory_levels/set.json` using `inventory_item_id` and `location_id`.
  The adapter fetches these from the first variant.
- **Price on variants:** `update_product_price()` updates the first variant's
  price. Product-level price is derived from variants.
- **Pagination:** Uses `since_id` cursor-based pagination (not page numbers).
  List endpoints return up to 250 items per request.
- **Collections as categories:** Shopify's "Custom Collections" and "Smart
  Collections" are mapped to `ProductCategory`. Collections have no parent/child
  hierarchy.
- **Tags as categories:** Product tags (comma-separated string) are also mapped as
  categories on the Product DTO.
- **Order identifiers:** Orders have both `id` (internal numeric) and
  `order_number` (display number). The mapper uses `order_number` as `order_id`.
- **Price conversion:** If `prices_include_vat` is enabled, prices are converted
  between gross (Shopify) and net (framework) using the configured VAT rate.
