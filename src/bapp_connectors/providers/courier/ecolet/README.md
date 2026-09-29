# eColet

Courier aggregator (panel.ecolet.ro): one account books DPD, Cargus, Sameday, FAN Courier, GLS, etc.

- **Base URL:** `https://panel.ecolet.ro/api` (staging: `https://staging.ecolet.ro/api`, credential `staging`)
- **Source:** OpenAPI spec behind https://panel.ecolet.ro/api/documentation (`docs/api-docs.json` v1.0.3),
  the v2 multipack guide, and the panel's own bundle for what the spec omits (listing orders).

## Credentials / settings

| Field | Notes |
|---|---|
| `client_id`, `client_secret` | OAuth client from the panel (`/account/oauth/clients`) |
| `username`, `password` | account email + password (OAuth password grant; the refresh token rotates) |
| `service` (setting) | Service slug, e.g. `dpd_standard`; empty = the cheapest service eColet offers for the shipment |
| `pickup_type` (setting) | `courier` (first available slot) or `self` (drop-off) |
| `awb_wait_seconds` (setting) | How long `generate_awb` polls for the AWB (default 30) |

## Flow (`generate_awb`)

1. Resolve eColet `locality_id` for sender and recipient (`/v1/locations/{cc}/localities/{q}`).
2. `POST /v2/add-parcel/reload-form` → availability, prices (strings with a comma decimal) and pickup slots per
   service slug. `errors` there block the order even with HTTP 200.
3. `POST /v2/add-parcel/send-order` → `order_to_send_id`. **Asynchronous**, sent once (`retry=False`).
4. Poll `GET /v1/order-to-send/{id}` until `ordered` (→ `order_id`) or `error`.
5. `GET /v1/order/{id}` → `awb`, price, courier; `GET /v1/order/{id}/download-waybill` → PDF (or ZPL,
   per the account's printer setting — only a PDF is returned as `label_pdf`).

A timeout while polling raises an error that says to check the panel: the booking may still go through.

## Shipment mapping

- `shipment.sender` is required by eColet; without it the account's default address-book entry is used.
- `shipment.extra`: `service`, `cod_amount`, `declared_value` (split across parcels), `content`, `observation`,
  `open_package`, `saturday_delivery`, `sms_notify`, `uit_code`, `package_type` (`package|envelope|pallet`).
- `Address.extra`: `name`/`company`, `contact_name`, `phone`, `email`, `number`, `block`, `entrance`, `floor`,
  `flat`, `map_point_id` (locker).
- Weight and dimensions are whole kg / cm, rounded up, minimum 1.

## Tracking / cancel / list

- Tracking and cancel go by AWB through `POST /v1/order/get-statuses-for-many-orders` (which also gives the
  order id cancel needs); cancel is `DELETE /v1/order/{id}`.
- Status slugs (no official list): `delivered`; `canceled`; `return`, `returned`, `delivered to sender` →
  returned; see `mappers.ECOLET_STATUS_MAP`.
- `GET /v1/order` (listing) is the panel's endpoint, not in the public spec — untested with an API token.
- No webhooks: tracking is polled.
