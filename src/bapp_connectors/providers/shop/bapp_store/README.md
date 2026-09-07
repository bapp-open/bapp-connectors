# Company Store (BAPP)

Catalog push, volume pricing rules and order pull for a BAPP Company Store tenant.

- **API:** the store's `/api/` (bapp_framework content-type reads and DirectTask endpoints)
- **Base URL:** `<store_url>/api/`
- **Auth:** `Authorization: Token <token>` plus `X-App-Slug: sync` on every call
- **Webhooks:** Supported (HMAC-SHA256 hex over the raw body in `X-BappStore-Signature`), events `order.created`, `order.updated`
- **Rate limit:** 10 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive | Role |
|-------|-------|----------|-----------|------|
| `store_url` | Store URL | Yes | No | endpoint (internal `*-st.sites.bapp.ro` host) |
| `token` | Sync Token | Yes | Yes | store API token scoped to the `sync` app |

## Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `prices_include_vat` | bool | `true` | Store prices are gross. |
| `vat_rate` | str | `0.21` | Decimal VAT rate for net/gross conversion. |
| `batch_size` | int | `100` | Products per CatalogSyncTask call; the store rejects more than 100 with 413. |
| `pause_seconds` | int | `1` | Pause between batches. |
| `publish_status` | select | `publish` | `publish` or `draft` for new products. |
| `sync_images` | bool | `true` | Send photo URLs (the store keeps URLs, no sideloading). |

Only `vat_rate` is consumed by this adapter. `prices_include_vat`, `batch_size`, `pause_seconds`, `publish_status` and `sync_images` are read by the caller (the BAPP panel sync service) when it builds the Product DTOs and slices batches; the adapter sends whatever it is given, up to the hard 100-record ceiling. `max_rolling_order_percent` rides in the `rules{}` body and is part of `policy_hash`.

## Endpoints used

| Client method | Request |
|---------------|---------|
| `test_auth` | `GET content-type/store.storecategory/?page_size=1` |
| `sync_task` | `POST tasks/store.CatalogSyncTask` with any of `categories`, `products`, `rules`, `webhook` |
| `list_categories` | `GET content-type/store.storecategory/?page_size=100`, then every `next` page |
| `find_products` | `GET content-type/store.storeproduct/?code=<sku>&page_size=100&page=<n>` |
| `export_orders` | `GET tasks/store.OrdersExportTask?since=&cursor=&limit=` |
| `export_order` | `GET tasks/store.OrderExportTask?number=` |
| `set_webhook` | `sync_task({"webhook": {"url", "secret"}})` |
| `push_customer_pricing` | `sync_task({"customers": [...], "customers_full": true})` |

A create carries `is_active`; an update carries `id`, `parent_id` and `name` only (spec 2.2), so a store-side activation toggle survives a rename. Reads of the two content-type viewsets are page-number paged: `page` and `page_size`, `page_size` capped at 100.

The sync task response is positional: `products[i]` answers `products[i]` of the request with `status` `created`, `updated` or `error` and an error `code` (`validation`, `unknown_category`, `invalid_price`, `external_id_conflict`). The codes travel opaquely: the mappers copy `code` into `BulkItemResult.error_code` and the adapter into `PermanentProviderError.code` without branching on any value, so all four behave alike. The task upserts and never prunes.

## Orders

`Order.items[i].unit_price` is the catalogue LIST price (net, converted from the store's gross), not what the customer was actually charged. `Order.total` is the volume-discounted total (also net, converted from the store's gross `total`). The two do not reconcile by summing the lines: for the shipped fixture the line sum is 9025.00 net against an order total of 8140.56 net, about 11 percent apart, because the store applies order-value-tier discounts that are not reflected per line.

The per-unit price actually charged is `Order.items[i].extra["unit_tier"]` -- a gross string, left unconverted because it is informational only. This is intentional: the spec has the panel re-derive line pricing from its own rules rather than trust the store's per-line figure, and the fixture arithmetic reconciles exactly against `unit_tier` and `extra["volume_discount_total"]`. A consumer that needs an accurate per-order revenue figure should use `Order.total`, not a sum of `Order.items`.

## Customer pricing

`push_customer_pricing(records, full=True)` replaces the store's per-customer volume levels.
A record is a normalised fiscal key plus resolved percentages -- an order-value percent and a
sparse SKU-to-percent map -- and carries no name, address or trading history. `full=True` means
the list is complete and the store drops every customer absent from it; that is how a customer
whose rolling window moved past their last large invoice loses their level.

The store must answer `customers_applied: true` or the adapter raises `PermanentProviderError`.
A store on an older build answers without the key, which reads as False, so an unsupported store
fails loudly instead of silently dropping the push.

## Errors

401/403 -> `AuthenticationError`; 429 -> retryable `RateLimitError` (matches the core HTTP client's own 429 handling, since `sync_task` bypasses it); other 4xx (400 malformed envelope, 413 over 100 products or 8 MB) -> `PermanentProviderError`; 5xx and timeouts -> retryable `ProviderError`. The adapter guards the 100-record half of the 413 rule client-side (`bulk_upsert_products` raises `ValueError`); the 8 MB envelope cap is not measured here, so a photo-heavy batch under 100 records can still come back 413 as a `PermanentProviderError`. Callers that send long photo lists should slice smaller than 100. `sync_task` is never retried by the HTTP layer because the store may have applied the batch before a timeout.

## Not supported

`delete_product`, `update_order_status`, `update_product_stock`, `update_product_price` raise `UnsupportedFeatureError`: the store never prunes products, so deletes deactivate instead; the engine uses full updates and bulk upsert for stock and price; and status echo to the store is a later version.

## Fixtures

`fixtures/` holds the cross-repo contract samples (`products_batch.json`, `rules.json`, `orders_export.json`, `pricing_cases.json`) and is their canonical home. The same files live in the company-store and aio-backend test trees; change them here, copy them over, and compare copies with `json.loads` rather than with a digest.
