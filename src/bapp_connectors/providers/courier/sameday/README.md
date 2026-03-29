# Sameday

Sameday courier integration for AWB generation, tracking, and shipment management. One of the largest courier services in Romania with same-day and next-day delivery options.

- **API version:** REST
- **Base URL:** `https://api.sameday.ro/api/`
- **Auth:** Custom token (POST `/authenticate` with `X-Auth-Username` / `X-Auth-Password` headers, returns a 12-hour token)
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `username` | API Username | Yes | No |
| `password` | API Password | Yes | Yes |

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `pickup_point_id` | Default Pickup Point ID | Int | _(none)_ | If not set, the default pickup point from the API will be used. |
| `service_id` | Default Service ID | Int | `7` | Sameday service ID. Default: 7 (24h). |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| Generate AWB | Yes | Creates AWB, returns tracking number + cost + PDF label |
| Get tracking | Yes | Returns tracking history via parcel status-history endpoint |
| Cancel shipment | Yes | Deletes AWB by AWB number |
| List shipments | Yes | Paginated AWB listing via client-awb-list |
| Download AWB PDF | Yes | Downloads label as inline PDF |
| List pickup points | Yes (client only) | Available via `client.get_pickup_points()` |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `authenticate` | Obtain auth token (12h TTL) |
| POST | `awb` | Generate a new AWB |
| DELETE | `awb/{awb_number}` | Cancel/delete an AWB |
| GET | `awb/download/{awb_number}/{format}/pdf/inline` | Download AWB label as PDF |
| GET | `client/parcel/{parcel_number}001/status-history` | Get tracking history for a parcel |
| GET | `client/pickup-points` | List available pickup points |
| GET | `client-awb-list` | List AWBs with pagination |

## Shipment Status Mapping

| Sameday Status | Framework Status |
|---|---|
| `ParcelDetails` | `CREATED` |
| `Picked up`, `PickedUp` | `PICKED_UP` |
| `InTransit` | `IN_TRANSIT` |
| `InDelivery` | `OUT_FOR_DELIVERY` |
| `Delivered` | `DELIVERED` |
| `Canceled`, `Cancelled` | `CANCELLED` |
| `InReturn`, `Returned` | `RETURNED` |
| `FailedAttempt` | `FAILED_DELIVERY` |

Unmapped statuses default to `IN_TRANSIT`.

## Pickup Point Resolution

The adapter resolves the pickup point for AWB generation in this order:

1. `shipment.extra["pickup_point_id"]` -- per-shipment override
2. `config["pickup_point_id"]` -- adapter-level setting
3. API default -- fetches pickup points from `client/pickup-points` and uses the one marked `defaultPickupPoint`
4. First available -- if no default is set, uses the first pickup point returned by the API

If no pickup point can be resolved, a `ValueError` is raised.

## API Quirks

- **Token authentication:** The token is obtained via `POST /authenticate` with credentials in custom headers (`X-Auth-Username`, `X-Auth-Password`), not in the body. All subsequent requests use `X-Auth-Token` header.
- **Token TTL:** Tokens are valid for 12 hours. The client refreshes 5 minutes before expiry. The `expire_at` field in the auth response is an ISO timestamp.
- **Parcel number suffix:** The tracking status endpoint appends `001` to the parcel number: `client/parcel/{parcel_number}001/status-history`. This is the Sameday convention for the first parcel in a multi-parcel AWB.
- **PDF label download is best-effort:** If the label download fails after AWB creation, the AWB is still returned without the PDF bytes.
- **Pagination:** `get_shipments()` supports cursor-based pagination. The cursor is the page number (as a string). The response includes `pages`/`totalPages`, `currentPage`/`page`, and `nrOfElements`/`totalElements`.
- **AWB cost:** The AWB generation response includes `awbCost`, which is mapped to `AWBLabel.cost`.
- **Extra payload overrides:** The following fields can be overridden via `shipment.extra`: `observation`, `cashOnDelivery`, `insuredValue`, `awbPayment`, `thirdPartyPickup`, `service`.
- **Default AWB payment:** Defaults to sender pays (`awbPayment: 1`).
- **Service ID 7:** The default service ID `7` corresponds to the standard 24-hour delivery service.
