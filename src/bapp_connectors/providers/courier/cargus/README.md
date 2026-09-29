# Cargus

UrgentOnline API `https://urgentcargus.azure-api.net/api` (test: `urgentcargusapitest.azure-api.net`) — AWB,
PDF label, tracking, cancel, listing by date.

- **Source:** the OpenAPI export of Cargus' Azure API Management portal (API "UrgentOnlineAPI", 81 operations),
  the official DocumentationAPIV3 PDF and the official Cargus WooCommerce plugin. Hosts and the gateway's 401
  checked live; no authenticated call (subscriptions are approval-gated, no public test credentials).
- **Auth:** `Ocp-Apim-Subscription-Key` on every call + `Authorization: Bearer <token>` from
  `POST LoginUser {UserName, Password}` (a JSON string, valid 24h). A 401 or the body `"Failed to authenticate!"`
  triggers one re-login, as in the official plugin.

## Credentials / settings

| Field | Notes |
|---|---|
| `subscription_key` | primary key of the portal subscription |
| `username`, `password` | WebExpress user |
| `pickup_location_id` | sender `LocationId`; empty = the first active point (`GET PickupLocations`) |
| `test` | use the test host |
| `service_id` (setting) | 34 Economic Standard (default), 35 Standard Plus, 36 Palet, 39 Multipiece; lockers force 38 |
| `cod_to_bank_account` (setting) | COD as `BankRepayment` (to the account) instead of `CashRepayment` (envelope) |
| `payer` (setting) | sender (1) / recipient (2) |
| `label_format` (setting) | A4 (0) / label 10x14 (1) |

## Mapping

- Recipient by **names** (`CountyName`, `LocalityName`, `StreetName`, `BuildingNumber`, `AddressText`,
  `CodPostal`), ids 0 — how the official plugin sends it.
- `TotalWeight` is an **int** (kg, rounded up); `ParcelCodes[]` one per piece, `Code "0"` (Cargus assigns),
  `Type` 1 = parcel / 0 = envelope; dimensions in cm.
- Ship & Go point: `recipient.extra.pickup_point_id` → `DeliveryPudoPoint`, service 38, no COD.
- `CustomString` carries `shipment.extra["reference"]` (comes back in tracking / COD reports).

## Quirks

- `POST Awbs/WithGetAwb` (full AWB objects, not just the barcode); sent once. 4xx refusals →
  `ValidationError`, 5xx stays `ProviderError`.
- Errors: a JSON array of messages, `{"Error"}` / `{"message"}`, or a bare string.
- Label: `GET AwbDocuments?barCodes=["..."]&type=PDF` → a JSON string with **base64**.
- Tracking: `GET AwbTrace?barCode=["..."]`. Cargus publishes no event list: 21 delivered (corroborated),
  the rest from an open-source adapter — see `mappers.map_event`.
- Cancel: `DELETE Awbs?barCode=` → `true`, `false` after the first scan.
- Listing: `Awbs/GetByDate` with `MM-dd-yyyy` dates (per the PDF), pages of 100 until a short page.
- AWBs join the point's open pickup order, closed at its `AutomaticEOD` (or `PUT Orders`, not implemented).
