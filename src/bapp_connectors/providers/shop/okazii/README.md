# Okazii

Okazii marketplace integration for orders and product management.

- **API version:** v2
- **Base URL:** `https://api.okazii.ro/v2/`
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
| Get products | No (managed via feed) |
| Update product stock | No (managed via feed) |
| Update product price | No (managed via feed) |
| Update order status | No |
| Get couriers | Yes (client only) |
| Get order courier / AWB | Yes (client only) |
| InvoiceAttachmentCapability | Yes |
| BulkUpdateCapability | No |
| WebhookCapability | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `countries` | List countries (used for auth test) |
| GET | `export_orders` | List orders (date range filter) |
| GET | `export_orders/{id}` | Get single order |
| GET | `order_awbs/{id}` | Get AWB for an order |
| GET | `bid_awb_couriers` | List available couriers |
| GET | `export_order_invoices/{id}` | Get invoices for an order |
| POST | `export_order_invoices/{id}` | Attach invoice (URL or file upload) |

## Order Status Mapping

Okazii order statuses come from the first bid in the order.

### Inbound mapping (Okazii -> Framework)

| Okazii Status | Framework Status |
|---|---|
| `new` | `PENDING` |
| `confirmed` | `ACCEPTED` |
| `canceled` | `CANCELLED` |
| `returned` | `RETURNED` |
| `delivered` | `DELIVERED` |
| `finished` | `DELIVERED` |

## Payment Method Mapping

Payment method is extracted from the first bid's `paymentMethod` field.

| Okazii Payment Method | Framework PaymentType |
|---|---|
| `ramburs_okazii` | `CASH_ON_DELIVERY` |
| `ramburs` | `CASH_ON_DELIVERY` |
| `card` | `ONLINE_CARD` |

Unmapped payment methods default to `OTHER`.

## Invoice Attachment

The `InvoiceAttachmentCapability` supports two modes via the client:
- **URL attachment:** `attach_invoice_url()` sends a JSON body with the invoice URL.
- **File upload:** `attach_invoice()` uploads a PDF file directly.

The adapter's `attach_invoice()` method uses the URL mode.

## API Quirks

- **Hydra-LD responses:** List endpoints return results in `hydra:member` arrays
  (JSON-LD format).
- **Products via feed only:** Okazii does not expose a REST API for product
  management. Products and stock are managed through XML/CSV product feeds.
  The `get_products()` method returns an empty result.
- **Bid-based orders:** Orders contain `bids` (auction/purchase items). The order
  status and payment method are extracted from the first bid.
- **Date filtering:** Orders are filtered by `date_from` and `date_to` query
  parameters in `YYYY-MM-DD` format.
- **Billing info:** Billing data can come from either `billingInfo` or
  `deliveryAddress` as a fallback. The CUI (tax ID) field is used for VAT ID.
- **Shipping cost:** Delivery price is included as a separate `OrderItem` with
  `item_id = "shipping"` and `extra.is_transport = True`.
- **Currency:** Hardcoded to `RON`.
