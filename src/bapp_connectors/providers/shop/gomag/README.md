# Gomag

Gomag e-commerce platform integration for orders, products, and inventory management.

- **API version:** v1
- **Base URL:** `https://api.gomag.ro/api/v1/`
- **Auth:** Custom headers (`ApiShop` + `Apikey`)
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `token` | API Key | Yes | Yes |
| `shop_site` | Shop Domain | Yes | No |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (paginated) | Yes |
| Get single order | Yes |
| Get products (paginated) | Yes |
| Update order status | Yes |
| Update product stock | No (API v1 limitation) |
| Update product price | No (API v1 limitation) |
| Get categories | Yes (client only) |
| Get order statuses | Yes (client only) |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `product/read/json` | List products (paginated) |
| GET | `order/read/json` | List orders / get single order |
| GET | `order/status/json` | Update order status |
| GET | `order/status/read/json` | List available order statuses |
| GET | `category/read/json` | List categories |

## Order Status Mapping

Gomag order statuses are **custom per shop** -- each connection can define its own
statuses. The mapping between Gomag statuses and framework `OrderStatus` values is
configurable via the connection config.

### Default inbound mapping (Gomag -> Framework)

| Gomag Status | Framework Status |
|---|---|
| `Comanda NEW` | `PENDING` |
| `Comanda email` | `PENDING` |
| `Comanda telefonica` | `PENDING` |
| `Comanda in asteptare` | `PENDING` |
| `Comanda depozitata` | `ACCEPTED` |
| `Comanda depozit` | `ACCEPTED` |
| `In curs de procesare` | `PROCESSING` |
| `Comanda in curs de livrare` | `SHIPPED` |
| `Livrata` | `DELIVERED` |
| `Comanda incheiata` | `DELIVERED` |
| `Anulata` | `CANCELLED` |
| `Retur` | `RETURNED` |
| `Returnata` | `RETURNED` |

### Default outbound mapping (Framework -> Gomag)

| Framework Status | Gomag Status |
|---|---|
| `PENDING` | `Comanda NEW` |
| `ACCEPTED` | `Comanda depozitata` |
| `PROCESSING` | `In curs de procesare` |
| `SHIPPED` | `Comanda in curs de livrare` |
| `DELIVERED` | `Livrata` |
| `CANCELLED` | `Anulata` |
| `RETURNED` | `Retur` |
| `REFUNDED` | `Retur` |

### Overriding status mapping

Each connection can override the defaults via `status_map_inbound` and
`status_map_outbound` in the connection config JSON:

```json
{
  "status_map_inbound": {
    "Statusul meu custom": "processing",
    "Expediat cu curier": "shipped"
  },
  "status_map_outbound": {
    "shipped": "Expediat cu curier",
    "delivered": "Finalizat"
  }
}
```

To discover available statuses for a shop, use the `get_order_statuses()` client
method which calls the `order/status/read/json` endpoint.

## Payment Method Mapping

| Gomag Payment Method | Framework PaymentType |
|---|---|
| `Plata ramburs` | `CASH_ON_DELIVERY` |
| `Ordin de Plata` | `BANK_TRANSFER` |
| `Plata cu cardul` | `ONLINE_CARD` |
| `Card online` | `ONLINE_CARD` |

Unmapped payment methods default to `OTHER`.

## API Quirks

- **Dict-keyed responses:** Gomag returns products and sometimes orders as a dict
  keyed by ID instead of a list. The mappers normalize this automatically.
- **Date formats:** The API returns dates in ISO format or `%Y-%m-%d %H:%M:%S`.
  Both are handled.
- **Currency:** Products don't include currency; orders use `currency_code` field
  (defaults to `RON`).
- **Status update endpoint:** Uses GET (not POST) for `order/status/json`.
