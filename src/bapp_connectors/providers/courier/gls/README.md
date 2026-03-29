# GLS

GLS courier integration for AWB generation, tracking, and shipment management. Supports multiple countries across Central and Eastern Europe.

- **API version:** JSON-RPC style (WCF)
- **Base URL:** `https://api.mygls.{country}/ParcelService.svc/json/` (country-specific)
- **Auth:** Custom (username + SHA-512 hashed password embedded in every request body)
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `username` | API Username | Yes | No |
| `password` | API Password | Yes | Yes |
| `client_number` | Client Number | Yes | No |
| `country` | Country Code (RO, HU, HR, CZ, SI, SK, RS) | Yes | No |

## Settings

| Field | Label | Type | Default | Choices | Description |
|-------|-------|------|---------|---------|-------------|
| `printer_type` | AWB Printer Format | Select | `Connect` | `A4_2x2`, `A4_4x1`, `Connect`, `Thermo` | Label format for AWB printing. |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| Generate AWB | Yes | Creates parcel via PrintLabels, returns tracking number + PDF label |
| Get tracking | Yes | Returns tracking history via GetParcelStatuses |
| Cancel shipment | Yes | Deletes parcel via DeleteLabels (requires ParcelId, not AWB number) |
| List shipments | Yes | Lists parcels within a date range via GetParcelList |
| Download labels | Yes (client only) | Re-download labels for existing parcels via `client.get_printed_labels()` |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `PrintLabels` | Generate AWB labels for parcels |
| POST | `DeleteLabels` | Delete/cancel a parcel by ParcelId |
| POST | `GetParcelStatuses` | Get tracking history for a parcel by AWB number |
| POST | `GetParcelList` | List parcels within a date range |
| POST | `GetPrintedLabels` | Download labels for already-generated parcels |

## Supported Countries

The base URL is determined by the `country` credential field:

| Country Code | Base URL |
|---|---|
| `RO` | `https://api.mygls.ro/ParcelService.svc/json/` |
| `HU` | `https://api.mygls.hu/ParcelService.svc/json/` |
| `HR` | `https://api.mygls.hr/ParcelService.svc/json/` |
| `CZ` | `https://api.mygls.cz/ParcelService.svc/json/` |
| `SI` | `https://api.mygls.si/ParcelService.svc/json/` |
| `SK` | `https://api.mygls.sk/ParcelService.svc/json/` |
| `RS` | `https://api.mygls.rs/ParcelService.svc/json/` |

## Shipment Status Mapping

GLS uses numeric status codes (01-99). The adapter maps these to framework `ShipmentStatus` values.

| GLS Code | Description | Framework Status |
|---|---|---|
| `01` | Handed over to GLS | `PICKED_UP` |
| `02` | Left parcel center | `IN_TRANSIT` |
| `03` | Reached parcel center | `IN_TRANSIT` |
| `04` | Expected delivery during the day | `OUT_FOR_DELIVERY` |
| `05` | Delivered | `DELIVERED` |
| `06`, `07` | Stored in parcel center | `IN_TRANSIT` |
| `11` | Consignee on holidays | `FAILED_DELIVERY` |
| `12` | Consignee absent | `FAILED_DELIVERY` |
| `14` | Reception closed | `FAILED_DELIVERY` |
| `15` | Not delivered lack of time | `FAILED_DELIVERY` |
| `16` | No cash available | `FAILED_DELIVERY` |
| `17` | Refused acceptance | `RETURNED` |
| `18` | Need address info | `FAILED_DELIVERY` |
| `20` | Wrong/incomplete address | `FAILED_DELIVERY` |
| `23`, `40` | Returned to sender | `RETURNED` |
| `51` | Data entered, not yet handed over | `CREATED` |
| `54` | Delivered to parcel box | `DELIVERED` |
| `55` | Delivered at ParcelShop | `DELIVERED` |
| `58` | Delivered at neighbour's | `DELIVERED` |
| `83` | Pickup data entered | `PICKED_UP` |
| `84` | Pickup label produced | `PICKED_UP` |
| `85` | Driver received pickup order | `OUT_FOR_DELIVERY` |
| `86` | Parcel reached center (pickup) | `IN_TRANSIT` |
| `92` | Delivered (pickup) | `DELIVERED` |
| `97` | Placed to parcellocker | `DELIVERED` |

Unmapped status codes default to `IN_TRANSIT`.

## API Quirks

- **All endpoints use POST:** GLS uses a JSON-RPC style API where every call is a POST with the full request payload (including credentials) in the body.
- **Password hashing:** The API requires the password as a SHA-512 hash represented as a list of byte values (e.g., `[104, 23, ...]`), not a hex string.
- **Authentication in every request:** Unlike token-based APIs, GLS requires `Username` and `Password` (hashed) fields in every single request body.
- **ParcelId vs AWB number:** `cancel_shipment()` requires the GLS-internal `ParcelId` (integer), not the AWB/tracking number. The `ParcelId` is returned in `AWBLabel.extra["parcel_id"]` after AWB generation.
- **Date format:** GLS uses Microsoft WCF date format: `/Date(1739142000000+0100)/` (millisecond timestamp with timezone offset).
- **Label bytes as int list:** The `Labels` field in responses is a list of integer byte values, not raw bytes or base64. The adapter converts this to `bytes` automatically.
- **Connection test:** Verified by calling `GetParcelList` and checking for `ErrorCode == -1` (authentication failure) in the error list, since GLS has no dedicated auth test endpoint.
- **Default date range:** `GetParcelList` defaults to the last 8 hours if no date range is provided.
- **COD support:** Cash-on-delivery is supported via `CODAmount`, `CODReference`, and `CODCurrency` fields in the parcel payload.
