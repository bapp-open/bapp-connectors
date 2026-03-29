# Vendigo

Vendigo marketplace integration for orders and product management.

- **API version:** v1
- **Base URL:** `https://my.vendigo.ro/api/v1/`
- **Auth:** Bearer token
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `token` | API Token | Yes | Yes |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (list) | Yes |
| Get single order | Yes |
| Get products (list) | Yes |
| Update product stock | No (not exposed via API) |
| Update product price | No (not exposed via API) |
| Update order status | No |
| Set order status | Yes (client only, via `set_order_status`) |
| Order acknowledge | Yes (client only) |
| InvoiceAttachmentCapability | Yes |
| BulkUpdateCapability | No |
| WebhookCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `groups/list` | List product groups (used as auth test) |
| GET | `orders/list` | List orders (date filter) |
| GET | `orders/{id}` | Get single order |
| POST | `orders/set_status` | Set order status (batch) |
| POST | `orders/{id}/attach_receipt` | Attach invoice URL to an order |
| GET | `products/list` | List products |
| GET | `products/by_external_id/{id}` | Get product by external ID |
| GET | `payment_options/list` | List payment options |
| GET | `delivery_options/list` | List delivery options |

## Order Status Mapping

### Inbound mapping (Vendigo -> Framework)

| Vendigo Status | Framework Status |
|---|---|
| `pending` | `PENDING` |
| `received` | `ACCEPTED` |
| `delivered` | `DELIVERED` |
| `canceled` | `CANCELLED` |

### Order acknowledgment

The client provides `order_acknowledge()` which sets the status to `received`.
The `set_order_status()` method sends a POST to `orders/set_status` with a
status string and a list of order IDs.

Note: `update_order_status()` on the adapter is not implemented, but the client
exposes `set_order_status()` directly.

## Payment Method Mapping

Vendigo uses numeric payment option IDs from a legacy system.

| Vendigo Payment Option ID | Framework PaymentType |
|---|---|
| `35385` | `PAYMENT_ORDER` |
| `8429` | `CASH_ON_DELIVERY` |

Other payment options default to `PAYMENT_ORDER`.

## Invoice Attachment

The `InvoiceAttachmentCapability` attaches an invoice URL to an order via
`POST /orders/{id}/attach_receipt` with `{"receipt_url": invoice_url}`.

## API Quirks

- **Price format:** Vendigo returns prices as strings like `"123,45 lei"` (Romanian
  format with comma decimal and currency suffix). The mapper's `_parse_price()`
  strips the `lei` suffix and converts commas to dots.
- **No pagination:** Product and order list endpoints return all items at once
  (no cursor or page parameters). `PaginatedResult.has_more` is always `false`.
- **Date filtering:** Orders are filtered by `date_from` query parameter in
  `YYYY-MM-DD` format.
- **Flat contact model:** Billing and shipping contacts use the same fields from
  the order root level (`client_first_name`, `client_last_name`, `email`, `phone`,
  `delivery_address`). Both billing and shipping contacts map to the same data.
- **Delivery address as string:** The delivery address is a single string field
  (`delivery_address`), not structured fields. The region is extracted from the
  first comma-separated segment.
- **Shipping cost:** Delivery cost (`delivery_cost`) is included as a separate
  `OrderItem` with `item_id = "shipping"` and `extra.is_transport = True`.
- **Currency:** Hardcoded to `RON`.
- **Product ID:** Uses `external_id` as the primary product ID when available,
  falling back to the internal `id`.
