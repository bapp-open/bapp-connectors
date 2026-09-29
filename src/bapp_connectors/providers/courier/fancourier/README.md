# FAN Courier

FAN Courier REST API v2 — AWB generation, PDF label, tracking, cancellation, daily AWB list.

- **Base URL:** `https://api.fancourier.ro`
- **Source:** official "API Documentation FAN Courier V2.0" (September 2025). **Not yet tested live**:
  `api.fancourier.ro` did not answer from the build machine (www.fancourier.ro did) — likely an IP filter.
- **Test account (public, on the production API):** username `clienttest`, password `testing`, clientId `7032158`.

## Credentials / settings

| Field | Notes |
|---|---|
| `username`, `password` | selfAWB login |
| `client_id` | selfAWB branch; empty = first branch from `/reports/branches` |
| `service` (setting) | Service **name**, default `Standard` (list: `/reports/services`) |
| `cod_to_bank_account` (setting) | With `cod_amount`, switch to the service's *Cont Colector* variant (COD wired to the bank account) |
| `payer` (setting) | `sender` / `recipient` |
| `label_format` (setting) | `A4` / `A5` / `A6` (A6 only with ePOD) |

## Shipment mapping

- `shipment.extra`: `service`, `cod_amount`, `declared_value`, `content`, `observation`, `options` (letters, e.g. `["V"]`
  for FANbox), `uit_code` (e-Transport), `cost_center`, `package_type="envelope"`.
- `recipient.extra`: `name`/`company`, `contact_name`, `phone`, `email`, `number`, `block`, `entrance`, `floor`, `flat`,
  `pickup_point_id` (FANbox / PayPoint / office → `pickupLocationId`).
- Weight is the parcels' total in whole kg (rounded up); dimensions are the largest parcel's, in cm.

## Quirks

- Login: `POST /login?username=&password=`; token valid 24h (`expiresAt`, Bucharest time, no zone), reused
  until then; a 401 triggers one re-login. No refresh endpoint.
- `POST /intern-awb` answers `{"response":[{awbNumber, tariff, errors}]}` per shipment; an error there comes
  with HTTP 200. Sent once (`retry=False`): a retry could create a second AWB.
- Label: `GET /awb/label?awbs[]=&pdf=1` returns raw PDF; without `pdf=1` it returns HTML.
- Tracking uses `awb[]`, the label `awbs[]`. Events are oldest first; the codes are not classified by FAN —
  `S2` delivered, `S16`/`S43` returned, a `returnAwbNumber` also means returned (see `mappers.FAN_EVENT_MAP`).
- `DELETE /awb?clientId=&awb=` works only before pickup.
- Listing: `/reports/awb` covers a single day; `get_shipments` walks day by day (cursor `YYYY-MM-DD:page`).
- Generating an AWB does **not** order a pickup (that is `POST /order`, not implemented).
