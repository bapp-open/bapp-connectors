# Trendyol

Trendyol marketplace integration for orders, products, and inventory management.

- **API version:** Integration API (current)
- **Base URL:** `https://apigw.trendyol.com/integration/`
- **Auth:** HTTP Basic Auth (username + password)
- **Webhooks:** Supported (no signature verification)
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive | Default |
|-------|-------|----------|-----------|---------|
| `username` | API Username | Yes | No | - |
| `password` | API Password | Yes | Yes | - |
| `seller_id` | Seller ID | Yes | No | - |
| `country` | Country Code | No | No | `RO` (choices: RO, DE, SA, AE, GR, SK, CZ) |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Get orders (paginated) | Yes |
| Get single order | Yes |
| Get products (paginated) | Yes |
| Update product stock | Yes (via batch price-and-inventory) |
| Update product price | Yes (via batch price-and-inventory) |
| Update order status | No |
| Get categories | Yes (client only) |
| BulkUpdateCapability | Yes |
| InvoiceAttachmentCapability | Yes |
| WebhookCapability | Yes (manifest only, no adapter implementation) |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `webhook/sellers/{sellerId}/webhooks` | List webhooks (used as auth test) |
| GET | `order/sellers/{sellerId}/orders` | List orders (paginated, with filters) |
| GET | `product/sellers/{sellerId}/products` | List products (paginated) |
| PUT | `product/sellers/{sellerId}/products/batch` | Batch update products (name, etc.) |
| POST | `inventory/sellers/{sellerId}/products/price-and-inventory` | Batch update price and stock |
| GET | `product/sellers/{sellerId}/products/batch-requests/{batchId}` | Get batch request result |
| GET | `product/product-categories` | List product categories |
| GET | `sellers/{sellerId}/common-label/query` | Read AWB / shipping label |
| POST | `sellers/{sellerId}/seller-invoice-links` | Attach invoice URL to an order |

## Order Status Mapping

### Inbound mapping (Trendyol -> Framework)

| Trendyol Status | Framework Status |
|---|---|
| `Created` | `PENDING` |
| `Picking` | `PROCESSING` |
| `Shipped` | `SHIPPED` |
| `Delivered` | `DELIVERED` |
| `Cancelled` | `CANCELLED` |
| `UnDelivered` | `CANCELLED` |

Note: `update_order_status` is not implemented. Trendyol manages order lifecycle
transitions on its own platform.

## Payment Method Mapping

Trendyol orders default to `ONLINE_CARD` as the payment type. The marketplace
handles all payments; sellers do not see payment method details.

## Bulk Update

The `BulkUpdateCapability` uses two different Trendyol endpoints depending on
the fields being updated:

- **Price/stock only:** `POST /inventory/sellers/{sellerId}/products/price-and-inventory`
  (uses `barcode` as identifier, supports `salePrice`, `listPrice`, `quantity`)
- **Product data (name, etc.):** `PUT /product/sellers/{sellerId}/products/batch`
  (uses `barcode` as identifier, supports `title` and other fields)

The adapter automatically routes each update to the appropriate endpoint.

## Invoice Attachment

The `InvoiceAttachmentCapability` attaches an invoice URL to an order via
`POST /sellers/{sellerId}/seller-invoice-links` with `shipmentPackageId` and
`invoiceLink`.

## API Quirks

- **Seller ID in URLs:** All API endpoints include the `seller_id` in the URL path.
- **Custom User-Agent:** The client sends `{seller_id} - BappConnectors` as the
  User-Agent header, which is required by Trendyol.
- **storeFrontCode header:** The `country` credential is sent as the
  `storeFrontCode` header on every request.
- **Epoch timestamps:** Order dates (`orderDate`) are Unix epoch milliseconds,
  not ISO strings. The mapper converts them via `datetime.fromtimestamp(ts / 1000)`.
- **Date filtering:** Orders can be filtered by `startDate` and `endDate` as
  epoch milliseconds in query parameters.
- **Pagination:** Uses 0-based `page` parameter. Responses include `totalPages`,
  `totalElements`, and `page` for cursor calculation.
- **Product identification:** Products are identified by `barcode` for
  price/inventory updates and `productMainId` for product data.
- **Currency:** Orders include `currencyCode` (defaults to `TRY`). Products do not
  include currency.
- **External URL:** Orders are linked to
  `https://partner.trendyol.com/ro/orders/shipment-packages/all?orderNumber={orderNumber}`.
- **AWB downloads:** The `read_awb()` method first fetches a label URL from the
  common-label endpoint, then downloads the PDF content from that URL using a
  separate HTTP request.
- **Webhook events:** The manifest declares `order.created`, `order.cancelled`,
  `order.shipped` events but webhooks have no signature verification.
