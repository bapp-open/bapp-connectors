# CEL.ro

CEL.ro marketplace integration for orders, products, and inventory management.

- **API version:** Marketplace API (current)
- **Base URL:** `https://api-mp.cel.ro/market_api/`
- **Auth:** Custom (login endpoint returns bearer token, passed in `AUTH` header)
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive | Default |
|-------|-------|----------|-----------|---------|
| `username` | API Username | Yes | No | - |
| `password` | API Password | Yes | Yes | - |
| `country` | Country Code | No | No | `RO` (choices: RO) |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (paginated) | Yes |
| Get single order | Yes |
| Get products (paginated) | Yes |
| Update order status | No |
| Update product stock | No (no documented endpoint) |
| Update product price | No (no documented endpoint) |
| Get categories | Yes (client only) |
| BulkUpdateCapability | No |
| InvoiceAttachmentCapability | No |
| WebhookCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `login/actionLogin` | Authenticate and obtain bearer token |
| POST | `orders/getOrders` | List orders (paginated, with filters) |
| POST | `orders/getOrder` | Get single order by ID |
| POST | `import/getProducts` | List products (paginated) |
| POST | `import/getSupplierCategories` | List supplier categories |

## Order Status Mapping

CEL.ro uses numeric order statuses.

### Inbound mapping (CEL.ro -> Framework)

| CEL Status (int) | Framework Status |
|---|---|
| `0` | `CANCELLED` |
| `1` | `PENDING` |
| `2` | `PROCESSING` |
| `3` | `SHIPPED` |
| `4` | `DELIVERED` |

## Payment Method Mapping

CEL.ro uses numeric payment mode IDs.

| CEL Payment Mode ID | Framework PaymentType |
|---|---|
| `1` | `CASH_ON_DELIVERY` |
| `2` | `BANK_TRANSFER` |
| `3` | `ONLINE_CARD` |
| `4` | `PAYMENT_ORDER` |

Unmapped payment methods default to `OTHER`.

## API Quirks

- **Token-based auth:** CEL uses a login endpoint (`login/actionLogin`) that returns
  a bearer token. The token is cached for the lifetime of the client instance and
  sent in the `AUTH` header as `Bearer {token}`.
- **All endpoints use POST:** Even read operations (orders, products, categories)
  use POST with JSON request bodies, not GET with query parameters.
- **Pagination:** Uses `start` / `limit` offsets in the JSON body, not page numbers.
- **Date filtering:** Orders can be filtered by `minDate` inside a `filters.date`
  object in the request body.
- **Currency:** Products do not include currency; orders derive currency from
  individual product line items (defaults to `RON`).
- **Country mapping:** The `country` credential maps to language headers
  (RO, BG, HU) but currently only `RO` is available as a choice.
