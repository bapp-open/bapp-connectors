# Altex Marketplace

Seller API v2.0 (`https://marketplace.altex.ro/v2.0`; staging `https://mkp-stage.altex.ro`, IP-allowlisted).

- **Source:** the Swagger 2.0 spec embedded in https://marketplace.altex.ro/api_doc (tag list: order, rma,
  catalog, offer, stock, courier, location). Host and error envelope checked live; no authenticated call.
- **Keys:** public + private key, issued by the Altex Marketplace team (marketplace@altex.ro).

## Signature (every request)

```
params     = query params (GET/DELETE) or body params (POST/PUT), minus the `media` file
params_str = http_build_query(params, '', '|', PHP_QUERY_RFC3986)
ddmm       = date('dm') in UTC
X-Request-Signature = ddmm + sha512_hex(public + "||" + sha512_hex(private) + "||" + params_str + "||" + ddmm)
```

`client.build_query` reproduces PHP's `http_build_query` (nested keys `a%5Bb%5D`, nulls skipped, RFC 3986,
`true`→`1`, `19.0`→`19`); the unit tests pin it to vectors computed with PHP 8.5. Multipart arrays are sent
as `key[]` fields so PHP rebuilds the array that was signed.

## What is implemented

| | |
|---|---|
| `get_orders(since)` | `GET sales/order/` by order date (`start_date`..today), then each order in full |
| `get_order(id)` | numeric Altex id = `Order.external_id`; `Order.order_id` = the `ATX...` code |
| `update_order_status` / `acknowledge_order` | `PUT sales/order/{id}/` `{status}`; cancel sends `cancellationReason` |
| `get_products` | the seller's **offers** (`product_id` = offer id; `extra.altex_product_id` = catalog product) |
| `update_product_stock` / `update_product_price` | per offer; price sets `price` and `selling_price` (VAT incl., RON) |
| `upload_invoice(order_id, pdf, number)` | multipart, PDF ≤ 2 MB, linked to the order lines |
| `attach_awb(order_id, pdf, number, courier)` | own AWB; courier matched by name in `sales/courier/` |
| `generate_awb(order_id, courier, sender, ...)` | Altex books the courier (`awb/generate`); returns the AWB number + base64 PDF |
| `list_locations()` | pickup locations, for `sender['address_id']` |
| `get_returns(since, until)` (ReturnsCapability) | `GET sales/rma/` (filter `created_at >=`, `until` cut locally); each RMA read in full and joined to its order for SKU/price |

## Mapping

- Order status: 1 new → PENDING, 2 in progress → ACCEPTED, 3/8 → PROCESSING, 4 → SHIPPED, 9 completed →
  DELIVERED, 6 → RETURNED, 7/10 → CANCELLED, 11 → REFUNDED; `raw_status` keeps the code.
- Payment: 1 COD, 2 wire, 3 card (paid), 4 Credex.
- Lines: unit price = `selling_price` (promo) or `catalog_price`, VAT included; `vat` rate; SKU =
  `seller_product_code`. **No EAN on lines, no email or postal code on orders.**
- `extra`: `shipping_tax`, `payment_tax` (COD surcharge), `delivery_mode` (4 = Altex courier, whose shipping is
  invoiced by Altex), `awbs`, `invoices`.

## Returns (RMA)

- Reason codes → unified `ReturnReason` (7 wrong item, 2 defective, 4 damaged, 3 missing parts, 10/9 not
  delivered, the rest → changed mind / ordered by mistake); status 1-6 (Registered…Visualized).
- An RMA line has only the product id + action + reason (no SKU/qty/price); the order is fetched to fill SKU
  and unit price. Refund is estimated (sum of money-back lines' prices), so `refund.estimated = True`.
- `created_date` is ISO in real answers, a unix int in the doc example — both handled.

## Not implemented / quirks

- No order webhooks (only product approve/reject) — orders are polled.
- Product creation (catalog + approval), categories/attributes, RMA invoice/return-AWB upload are not wired yet.
- Invoice / AWB delete work per order, not per document.
- Envelope `{message, status, data}`; `message` can be a list, a dict keyed by row, or a string. Success codes
  are 200/201/202 — `status == "success"` is checked too.
