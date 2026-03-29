# eMAG

eMAG marketplace integration for orders, products, and inventory management.

- **API version:** v3
- **Base URL:** `https://marketplace-api.emag.{country}/api-3/` (per-country)
- **Auth:** HTTP Basic Auth (username + password)
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive | Default |
|-------|-------|----------|-----------|---------|
| `username` | API Username | Yes | No | - |
| `password` | API Password | Yes | Yes | - |
| `country` | Country Code | No | No | `RO` (choices: RO, BG, HU, PL) |

## Per-Country Base URLs

| Country | Base URL |
|---------|----------|
| RO | `https://marketplace-api.emag.ro/api-3/` |
| BG | `https://marketplace-api.emag.bg/api-3/` |
| HU | `https://marketplace-api.emag.hu/api-3/` |
| PL | `https://marketplace-api.emag.pl/api-3/` |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (paginated) | Yes |
| Get single order | Yes |
| Get products (paginated) | Yes |
| Update product stock | Yes |
| Update product price | Yes |
| Update order status | Yes |
| Acknowledge order | Yes |
| Get categories | Yes (client only) |
| Get couriers | Yes (client only) |
| Get product count | Yes (client only) |
| Get VAT list | Yes (client only) |
| AWB PDF download | Yes (client only) |
| BulkUpdateCapability | Yes |
| InvoiceAttachmentCapability | Yes |
| WebhookCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `order/read` | List orders (paginated, with filters) |
| POST | `order/save` | Update order status |
| POST | `order/attachments/save` | Attach invoice URL to an order |
| POST | `product_offer/read` | List product offers (paginated) |
| POST | `product_offer/save` | Create/update product offers (batch) |
| POST | `product_offer/count` | Get total product offer count |
| POST | `category/read` | List categories |
| POST | `courier_accounts/read` | List available courier accounts |
| POST | `vat/read` | List VAT rates |
| POST | `awb/read_pdf` | Download AWB PDF for an order |

## Order Status Mapping

eMAG uses fixed numeric status codes. The mapping is configurable per connection
via `status_map_inbound` and `status_map_outbound` in the connection config.

### Default inbound mapping (eMAG -> Framework)

| eMAG Status | Meaning | Framework Status |
|---|---|---|
| `0` | Cancelled/storno | `CANCELLED` |
| `1` | New | `PENDING` |
| `2` | In progress | `ACCEPTED` |
| `3` | Prepared | `SHIPPED` |
| `4` | Finalized | `DELIVERED` |
| `5` | Returned | `RETURNED` |

### Default outbound mapping (Framework -> eMAG)

| Framework Status | eMAG Status |
|---|---|
| `PENDING` | `1` |
| `ACCEPTED` | `2` |
| `PROCESSING` | `2` |
| `SHIPPED` | `3` |
| `DELIVERED` | `4` |
| `CANCELLED` | `0` |
| `RETURNED` | `5` |
| `REFUNDED` | `5` |

### Overriding status mapping

Each connection can override the defaults via `status_map_inbound` and
`status_map_outbound` in the connection config JSON:

```json
{
  "status_map_inbound": {
    "3": "processing"
  },
  "status_map_outbound": {
    "shipped": "3"
  }
}
```

## Payment Method Mapping

Payment type is resolved by `payment_mode_id` (numeric, preferred) with a fallback
to `payment_mode` (string).

### By payment_mode_id (primary)

| payment_mode_id | Framework PaymentType |
|---|---|
| `1` | `CASH_ON_DELIVERY` |
| `2` | `BANK_TRANSFER` |
| `3` | `ONLINE_CARD` |

### By payment_mode string (fallback)

| eMAG Payment Mode | Framework PaymentType |
|---|---|
| `online_card` / `card` | `ONLINE_CARD` |
| `bank_transfer` / `wire_transfer` | `BANK_TRANSFER` |
| `cash_on_delivery` / `cod` / `ramburs` | `CASH_ON_DELIVERY` |

Unmapped payment methods default to `OTHER`.

## Bulk Update

The `BulkUpdateCapability` sends all product updates in a single
`product_offer/save` API call. Each item is identified by `part_number` (barcode).
Supported fields: `sale_price`, `stock` (per warehouse), `name`.

## Invoice Attachment

The `InvoiceAttachmentCapability` attaches an invoice URL to an order via
`order/attachments/save`. The `attachment_type` defaults to `1` (invoice),
and `force_download` is enabled.

## API Quirks

- **POST for reads:** eMAG uses POST for most read operations with JSON filter
  payloads, not GET with query parameters.
- **Pagination:** Uses `currentPage` / `itemsPerPage` in request body. Responses
  include `noOfPages` and `noOfItems` for calculating next page.
- **`is_complete=1`:** Orders are fetched with `is_complete=1` to only return
  fully populated order data.
- **Payment status:** The `payment_status` field is numeric: `0` = unpaid,
  `1` = paid.
- **Stock per warehouse:** Stock updates require a `warehouse_id` (defaults to `1`).
- **Country-scoped URLs:** The base URL domain changes per country. The adapter
  overrides `http_client.base_url` at runtime based on the `country` credential.
- **Response format:** All responses are wrapped in `{isError, messages, results,
  currentPage, noOfPages, noOfItems}` and parsed via the `EmagApiResponse` model.
- **IP whitelist:** eMAG requires server IPs to be whitelisted in the marketplace
  portal. The `EmagIPWhitelistError` is raised when the IP is not allowed.
- **Status codes are integers:** Unlike most shop providers that use string status
  names, eMAG uses numeric status codes (0-5). These are stored as strings in
  `StatusMapper` for compatibility.
