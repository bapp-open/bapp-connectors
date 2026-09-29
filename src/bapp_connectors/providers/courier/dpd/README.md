# DPD Romania

Web API `https://api.dpd.ro/v1` (the Speedy / DPD BG platform) — shipment (AWB), PDF label, tracking, cancel.

- **Source:** official reference https://api.dpd.ro/api/docs/ + JSON Schema bundle (`/v1/schema`), the official
  DPD Romania WooCommerce plugin, recorded RO traffic. Host and error shape checked live; no authenticated call
  (no public test account — DPD issues test accounts by e-mail, on the same host).
- **Auth:** no token — `userName` / `password` in every POST body (`language: EN`).
- **Errors:** HTTP **200** with `{"error": {context, message, id, code, component}}`; auth failures are
  `code: 1` with an "authenticate" message → `AuthenticationError`; other refusals → `DpdApiError`
  (a `ValidationError` from `generate_awb`).

## Credentials / settings

| Field | Notes |
|---|---|
| `username`, `password` | API user |
| `client_id` | sending object from `/client/contract`; empty = the user's default object |
| `service_id` (setting) | default 2505 DPD STANDARD (from the official plugin; the contract decides — `/services`) |
| `payer` (setting) | `SENDER` / `RECIPIENT` |
| `paper_size` (setting) | `A6` / `A4` / `A4_4xA6` |
| `package` (setting) | free text required by DPD, default `BOX` |

## Addresses

- Site: `/location/site` by postcode (unique), else by name + county; unresolved → `siteName` + `postCode`.
- Street: `/location/street` by the bare name (`split_street` strips "Str.", "Bd."... and the trailing number);
  unmatched → the whole text goes to `addressNote` (manual processing at DPD, possible delay).
- Text without diacritics (DPD transliterates outside Windows-1251). Phone: digits and `+`.
- Private person → `clientName`; company → `privatePerson: false`, `clientName` = company, `contactName` = person
  (`contactName` is forbidden for private persons).
- Office / locker: `recipient.extra.pickup_point_id` → `pickupOfficeId` (no address).

## Quirks

- `POST /shipment` is sent once (`retry=False`); `autoAdjustPickupDate: true` avoids `collection-term-expired`.
- COD: `{amount, currencyCode: RON, processingType: CASH}`; the contract needs a COD annex.
- `/print` answers raw PDF, or JSON `{"error"}` with 200 — decided by Content-Type.
- Tracking (`/track`, max 10 parcels): `-14` delivered, `124` delivered back to sender, `111` return in progress,
  `123` refused, `128` cancelled; see `mappers.DPD_OPERATION_MAP`.
- Cancel (`/shipment/cancel`, comment required) only before pickup is ordered.
- **No listing by date** — `get_shipments` returns nothing; creating a shipment does not order a pickup
  (`POST /pickup`, not implemented; many contracts have a standing daily pickup).
