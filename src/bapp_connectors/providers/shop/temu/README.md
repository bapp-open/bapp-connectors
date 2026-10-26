# Temu (Partner Platform, local-to-local seller)

Family `shop`. Covers products (create v3 / update / stock / price / delete), orders, customer
decryption, order amounts, webhooks, fulfillment (own courier or Temu label), invoice upload,
after-sales (returns) and settlement reports.

## Credentials

| Field | Where it comes from |
|---|---|
| `app_key`, `app_secret` | Partner Platform (`partner-eu.temu.com` for EU, `partner-us` / `partner` for US / global) → APP Management → your self-developed app. |
| `access_token` | Seller Center → System Management → Authorization Management → *Authorize a new app* → pick the app, tick the permissions, *Submit*, copy the token. Scopes are frozen at authorization: tick products, orders, **order amounts** (`temu.order.amount.v2.query`), logistics, after-sales, finance, tax invoice. Valid about one year. |
| `region` | `eu` (default), `us`, `global` — selects the router host. |
| `mall_id` | Filled in automatically on the connection test (`detect_credentials`). Used as the connection's endpoint display. |

`test_connection()` reports the mall name, the token expiry and `details["missing_scopes"]`: the
APIs this adapter calls that the token does not cover.

## Webhooks

1. Partner Platform → Webhook: set the callback URL to the host's generic endpoint for the
   connection (`https://<host>/webhooks/<connection_id>/temu/`) and enable the events.
2. `register_webhook(url, events)` then activates the events on the shop
   (`bg.tmc.message.update`); Temu has no API to set the URL itself.
3. Messages carry `x-tm-app-key`, `x-tm-event-code`, `x-tm-timestamp`, `x-tm-signature`,
   `x-tm-ext-param`; the body `eventData` is AES-128-CBC (key = IV = first 16 bytes of the app
   secret) + base64, signed with HMAC-SHA256 over the decrypted payload and the headers
   (signature method `temu-hmac-aes`, verified by the adapter). The parsed event's
   `payload["id"]` is the parent order sn.

## Test environment

Temu has no sandbox. The documentation page *Sandbox Test Shops* lists "Developer Test Shops":
real shops with fixed credentials per country (the RO one has hundreds of test orders), reachable
from any IP. Use them for development; never put their values in this repository.

## Known API traps (verified live)

- Order list/detail carry **no amounts**; prices come only from `temu.order.amount.v2.query`
  (separate scope) or `temu.pay.tax.invoice.detail.query` (self-billing merchants).
- `bg.local.goods.list.query` without `goodsSearchType` + `statusFilterType` answers `result: null`.
- `bg.aftersales.parentaftersales.list.get` needs a `createAtStart/createAtEnd` window (seconds).
- `temu.finance.mall.bill.task.create` may answer `200040005 Service not supported` for a shop;
  `get_financial_transactions` then raises `UnsupportedFeatureError`.
- Signed document URLs (labels, report files) expire after 10 minutes and need the `toa-*` headers.
