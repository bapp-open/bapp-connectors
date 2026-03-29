# Colete Online

Colete Online courier aggregator integration for AWB generation, tracking, and shipment management. Routes shipments to the best-priced courier (FAN Courier, Sameday, DPD, Cargus, etc.) based on service selection.

- **API version:** v1
- **Base URL:** `https://api.colete-online.ro/v1/`
- **Auth:** OAuth2 client credentials (token endpoint: `https://auth.colete-online.ro/token`)
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `client_id` | Client ID | Yes | No |
| `client_secret` | Client Secret | Yes | Yes |

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `staging` | Use Staging Environment | Bool | `true` | When enabled, orders are created in the staging environment. |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| Generate AWB | Yes | Creates order, returns tracking number + PDF label |
| Get tracking | Yes | Returns tracking history via order status endpoint |
| Cancel shipment | No | API does not expose a cancel/delete endpoint |
| List shipments | No | API does not expose an order listing endpoint (returns empty) |
| Price estimation | Yes (client only) | Available via `client.get_price()` |
| List services | Yes (client only) | Available via `client.get_services()` |
| List addresses | Yes (client only) | Available via `client.get_addresses()` |
| Account balance | Yes (client only) | Available via `client.get_balance()` |
| Location search | Yes (client only) | Search by country + needle |
| Shipping points | Yes (client only) | List localities and points by county |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `https://auth.colete-online.ro/token` | OAuth2 token (Basic auth, client_credentials grant) |
| POST | `staging/order` or `order` | Create a shipping order / generate AWB |
| GET | `staging/order/status/{uniqueId}` or `order/status/{uniqueId}` | Get order status / tracking |
| GET | `staging/order/awb/{uniqueId}?formatType=A4` or `order/awb/{uniqueId}` | Download AWB label as PDF |
| POST | `order/price` | Get price estimates for an order |
| GET | `service/list` | List available courier services |
| GET | `address` | List saved addresses |
| GET | `user/balance` | Get account balance |
| GET | `search/location/{countryCode}/{needle}` | Search for a location |
| GET | `search/city/{countryCode}/{county}/{needle}` | Search for a city |
| POST | `shipping-points/localities-list` | List localities with shipping points |
| POST | `shipping-points/list/{county}` | List shipping points in a county |

## Shipment Status Mapping

Colete Online uses various status strings depending on the underlying courier. The adapter normalizes these to framework `ShipmentStatus` values.

| Colete Online Status | Framework Status |
|---|---|
| `new`, `pending`, `processing`, `confirmed` | `CREATED` |
| `picked_up`, `pickedup` | `PICKED_UP` |
| `in_transit`, `intransit` | `IN_TRANSIT` |
| `in_delivery`, `out_for_delivery` | `OUT_FOR_DELIVERY` |
| `delivered` | `DELIVERED` |
| `cancelled`, `canceled` | `CANCELLED` |
| `returned` | `RETURNED` |
| `failed`, `failed_delivery` | `FAILED_DELIVERY` |

Unmapped statuses default to `IN_TRANSIT`.

## API Quirks

- **Staging vs production:** All order endpoints have separate staging paths (`staging/order` vs `order`). Controlled by the `staging` setting (defaults to `true`).
- **OAuth2 token lifecycle:** Token is acquired via `POST https://auth.colete-online.ro/token` with Basic auth (base64-encoded `client_id:client_secret`). The client refreshes the token 5 minutes before expiry.
- **Unique ID vs tracking number:** Order creation returns both a `uniqueId` (internal) and a `trackingNumber` (AWB). The `uniqueId` is required for status checks and label downloads. It is stored in `AWBLabel.extra["unique_id"]`.
- **No cancel endpoint:** The API does not expose a shipment cancellation endpoint. Cancellation must be done through the Colete Online dashboard or the underlying courier directly.
- **No order listing:** The API does not provide an endpoint to list past orders. `get_shipments()` returns an empty result.
- **PDF label download is best-effort:** If the label PDF download fails after AWB creation, the AWB is still returned without the PDF bytes.
- **Courier aggregator model:** Colete Online routes to the cheapest courier via `service.selectionType` (default `bestPrice`). You can restrict to specific couriers via `serviceIds`.
- **Date formats:** The API may return dates in ISO format, `%Y-%m-%dT%H:%M:%S`, or `%Y-%m-%d %H:%M:%S`. The mapper handles all variants.
