# Magento

Magento 2 / Adobe Commerce integration for orders, products, categories, and inventory management.

- **API version:** REST V1
- **Base URL:** `https://{domain}/rest/{store_code}/V1/`
- **Auth:** Bearer token (Integration Access Token from Magento Admin)
- **Webhooks:** Not supported
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `domain` | Store URL (e.g. https://myshop.com) | Yes | No |
| `access_token` | Integration Access Token | Yes | Yes |

## Settings

| Setting | Label | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `store_code` | Store Code | str | `default` | Magento store view code (e.g., 'default', 'en', 'ro'). Used in the API URL path. |
| `prices_include_vat` | Catalog Prices Include VAT | bool | `false` | Whether Magento catalog prices include tax (Stores > Config > Tax > Catalog Prices). |
| `vat_rate` | VAT Rate | str | `0.19` | VAT rate as decimal (e.g., 0.19 for 19%). |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (paginated) | Yes |
| Get single order | Yes |
| Update order status | Yes (via order comments) |
| Get products (paginated) | Yes |
| Update product stock | Yes |
| Update product price | Yes |
| BulkUpdateCapability | Yes |
| ProductCreationCapability | Yes |
| ProductFullUpdateCapability | Yes |
| CategoryManagementCapability | Yes |
| AttributeManagementCapability | Yes |
| VariantManagementCapability | Yes |
| RelatedProductCapability | Yes |
| WebhookCapability | No |
| OAuthCapability | No |
| InvoiceAttachmentCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `store/storeConfigs` | Connection test |
| GET | `products` | List products (searchCriteria) |
| GET | `products/{sku}` | Get single product by SKU |
| POST | `products` | Create product |
| PUT | `products/{sku}` | Update product |
| DELETE | `products/{sku}` | Delete product |
| GET | `stockItems/{sku}` | Get stock info |
| PUT | `products/{sku}/stockItems/{itemId}` | Update stock |
| GET | `orders` | List orders (searchCriteria) |
| GET | `orders/{id}` | Get single order |
| POST | `orders/{id}/comments` | Add comment / change order status |
| GET | `categories` | Get category tree |
| GET | `categories/list` | Flat list of categories |
| POST | `categories` | Create category |
| GET | `products/attributes` | List attribute definitions |
| GET | `products/attributes/{code}` | Get attribute |
| POST | `products/attributes` | Create attribute |
| GET | `products/attributes/{code}/options` | Get attribute options |
| POST | `products/attributes/{code}/options` | Add attribute option |
| GET | `configurable-products/{sku}/children` | Get variant children |
| POST | `configurable-products/{sku}/child` | Link variant child |
| DELETE | `configurable-products/{sku}/children/{childSku}` | Remove variant child |
| GET | `products/{sku}/links/{type}` | Get related/upsell/crosssell links |
| POST | `products/{sku}/links` | Set product links |
| POST | `products/{sku}/media` | Add product image |

## Order Status Mapping

Magento uses string-based order statuses. The adapter uses `StatusMapper` for
configurable status mapping.

### Default inbound mapping (Magento -> Framework)

| Magento Status | Framework Status |
|---|---|
| `pending` | `PENDING` |
| `pending_payment` | `PENDING` |
| `holded` | `PENDING` |
| `payment_review` | `PENDING` |
| `processing` | `PROCESSING` |
| `complete` | `DELIVERED` |
| `closed` | `REFUNDED` |
| `canceled` | `CANCELLED` |
| `fraud` | `CANCELLED` |

### Default outbound mapping (Framework -> Magento)

| Framework Status | Magento Status |
|---|---|
| `PENDING` | `pending` |
| `ACCEPTED` | `processing` |
| `PROCESSING` | `processing` |
| `SHIPPED` | `complete` |
| `DELIVERED` | `complete` |
| `CANCELLED` | `canceled` |
| `REFUNDED` | `closed` |
| `RETURNED` | `closed` |

### Overriding status mapping

Each connection can override the defaults via `status_map_inbound` and
`status_map_outbound` in the connection config JSON:

```json
{
  "status_map_inbound": {
    "my_custom_status": "processing"
  },
  "status_map_outbound": {
    "shipped": "my_custom_shipped"
  }
}
```

## Payment Method Mapping

| Magento Payment Method | Framework PaymentType |
|---|---|
| `checkmo` | `PAYMENT_ORDER` |
| `banktransfer` | `BANK_TRANSFER` |
| `cashondelivery` | `CASH_ON_DELIVERY` |
| `stripe_payments` | `ONLINE_CARD` |
| `braintree` | `ONLINE_CARD` |
| `paypal_express` | `ONLINE_CARD` |
| `authorizenet_directpost` | `ONLINE_CARD` |

Unmapped payment methods default to `OTHER`.

## API Quirks

- **SKU-based product identification:** Magento identifies products by SKU (not
  numeric ID). The adapter resolves entity IDs to SKUs when needed. SKU values
  in API URLs are URL-encoded.
- **searchCriteria pagination:** All list endpoints use `searchCriteria[pageSize]`,
  `searchCriteria[currentPage]`, and `searchCriteria[filterGroups]` query parameters.
- **Category tree:** Categories form a tree with `children_data`. The adapter
  flattens this into a list with `parent_id`. Root categories (parent_id 0 or 1)
  have `parent_id = None`.
- **Stock is separate:** Stock lives on `extension_attributes.stock_item`, not on
  the product itself. Updates use `PUT /products/{sku}/stockItems/{itemId}`.
- **Order status via comments:** Order status changes are done by posting a comment
  with the new status to `POST /orders/{id}/comments`.
- **Configurable products:** Variants are "simple" products linked to a
  "configurable" parent via `/configurable-products/{sku}/child`. When listing
  order items, the adapter skips parent configurable items (keeps simple children
  only).
- **Custom attributes:** Stored as `[{attribute_code, value}]` arrays on products.
  The mapper uses `_get_custom_attr()` to extract values like `description`, `ean`,
  or `barcode`.
- **Price conversion:** If `prices_include_vat` is enabled, the adapter converts
  between gross (Magento) and net (framework) prices using the configured VAT rate.
- **Store view scoping:** The `store_code` setting is injected into the URL path
  (`/rest/{store_code}/V1/`), allowing requests to target a specific store view.
- **Order identifiers:** Orders have both `entity_id` (internal numeric) and
  `increment_id` (display number). The mapper uses `increment_id` as `order_id`.
