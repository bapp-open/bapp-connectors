# Netopia

Romanian payment gateway (Netopia Payments / mobilPay) for online card payments with JSON API and IPN notifications.

- **API version:** JSON API (v2)
- **Base URL:** `https://secure.mobilpay.ro/pay/` (live), `https://sandboxsecure.mobilpay.ro/pay/` (sandbox)
- **Auth:** API key in `Authorization` header + POS signature in request body
- **Webhooks:** Supported (IPN JSON POST, no HMAC signature)
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `api_key` | API Key | Yes | Yes |
| `pos_signature` | POS Signature | Yes | Yes |
| `sandbox` | Sandbox Mode | No | No |

The `sandbox` credential accepts `"true"`, `"1"`, or `"yes"` (case-insensitive) to
enable the sandbox environment. Defaults to `"true"`.

## Settings

| Field | Label | Type | Default | Required |
|-------|-------|------|---------|----------|
| `notify_url` | Notification URL | String | — | No |
| `redirect_url` | Redirect URL | String | — | No |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Create checkout session | Yes (JSON API) |
| Get payment status | Yes (`payment/status` endpoint) |
| Refund | No (raises `UnsupportedFeatureError`) |
| Webhook verification (IPN) | Yes (structure check only) |
| Webhook parsing (IPN) | Yes |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `payment/card/start` | Start a new payment (returns `paymentURL`) |
| POST | `payment/status` | Get payment status by NTP ID |

## Payment Flow

1. `create_checkout_session()` calls `payment/card/start` with order details
2. Netopia returns a `paymentURL` where the customer should be redirected
3. Customer completes payment on Netopia's hosted page
4. Netopia POSTs IPN JSON notification to `notify_url`
5. Verify IPN with `verify_webhook()`, parse with `parse_webhook()`
6. Optionally query status later with `get_payment(ntp_id)`

The returned `CheckoutSession.extra` contains:
- `ntp_id` -- Netopia's internal transaction ID
- `status` -- initial status from the start response

## Payment Status Mapping

### Netopia status codes

| Status Code | Raw Status | Framework Status |
|-------------|------------|------------------|
| `0` | `pending` | `pending` |
| `3` | `paid_pending` | `processing` |
| `5` | `confirmed` | `completed` |
| `12` | `cancelled` | `cancelled` |
| `15` | `credit` | `refunded` |

### Webhook event type mapping

| Netopia Status | WebhookEventType |
|----------------|------------------|
| `confirmed` | `PAYMENT_COMPLETED` (via `ORDER_UPDATED`) |
| `paid_pending` | `ORDER_UPDATED` |
| `cancelled` | `ORDER_CANCELLED` |
| `credit` | `ORDER_UPDATED` |

## Request Payload Structure

The `payment/card/start` endpoint expects a nested JSON payload:

```json
{
  "config": {
    "emailTemplate": "default",
    "cancelUrl": "...",
    "notifyUrl": "...",
    "redirectUrl": "...",
    "language": "ro"
  },
  "payment": {
    "options": {"installments": 0, "bonus": 0},
    "instrument": null,
    "data": {}
  },
  "order": {
    "posSignature": "...",
    "orderID": "...",
    "description": "...",
    "amount": 100.00,
    "currency": "RON",
    "billing": { ... },
    "shipping": { ... }
  }
}
```

## API Quirks

- **No HMAC on IPN:** Unlike EuPlatesc and LibraPay, Netopia does not sign IPN
  notifications with HMAC. Verification only checks that the payload is valid JSON
  containing expected fields (`payment`, `order`, or `status`). Security relies on the
  `notify_url` being a non-guessable server-side endpoint.
- **Refunds not supported programmatically:** The adapter raises
  `UnsupportedFeatureError`. Refunds must be processed via the Netopia admin panel or
  are handled through the `credit` IPN callback (status code 15).
- **Sandbox mode via credentials:** The `sandbox` flag is a credential field (not a
  setting), which switches the base URL between live and sandbox environments.
- **`test_connection()` uses a minimal payment call:** Netopia has no dedicated auth-test
  endpoint. The client attempts a minimal `start_payment` call to verify credentials.
- **POS signature in body:** The `pos_signature` is sent inside the JSON request body
  (in `order.posSignature`), not as a header.
- **Auth header format:** The API key is sent as a Bearer token in the `Authorization`
  header. When the registry provides an `http_client`, the adapter overrides its auth to
  ensure `BearerAuth` is applied (since `CUSTOM` auth strategy means `NoAuth` by default).
- **Country as integer:** The billing `country` field is an integer code (e.g., `1` for
  Romania), not an ISO country code string.
- **Currency uppercased:** The adapter uppercases the currency code before sending to the
  API.
