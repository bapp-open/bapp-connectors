# Netopia

Romanian payment gateway (Netopia Payments / mobilPay) for online card payments with JSON API and IPN notifications.

- **API version:** JSON API (v2)
- **Base URL:** `https://secure.mobilpay.ro/pay/` (live), `https://secure.sandbox.netopia-payments.com/` (sandbox)
- **Auth:** API key in `Authorization` header + POS signature in request body
- **Webhooks:** Supported (IPN JSON POST, RS512 JWT in `Verification-Token`, verified with the `public_key` credential)
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
| Get payment status | Yes (`operation/status`) |
| Refund (full or partial) | Yes (`operation/credit`) |
| Cancel an uncaptured payment | Yes, `cancel_payment()` (adapter method, not on `PaymentPort`) |
| List transactions | **No** — the API has no listing, report or settlement endpoint |
| Webhook verification (IPN) | Yes — RS512 JWT, fails closed without `public_key` |
| Webhook parsing (IPN) | Yes |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `payment/card/start` | Start a new payment (returns `paymentURL`) |
| POST | `operation/status` | Payment status by NTP ID (also used by `test_connection`) |
| POST | `operation/credit` | Refund, full or partial |
| POST | `operation/void` | Cancel a pre-authorized (status 2) payment |
| POST | `operation/expire` | Close a started, never-paid payment |

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

Codes come from the official SDK (`netopiapayments/composer`, `IPN.php`). The
status lives in `payment.status`; a top-level `status` is only a fallback.

| Code | Raw status | Framework status | WebhookEventType |
|------|------------|------------------|------------------|
| 1 | `new` | `pending` | `PAYMENT_PENDING` |
| 2 | `opened` (pre-authorized) | `authorized` | `PAYMENT_PENDING` |
| 3 | `paid` | `completed` | `PAYMENT_COMPLETED` |
| 4 | `canceled` (void) | `cancelled` | `PAYMENT_FAILED` |
| 5 | `confirmed` | `completed` | `PAYMENT_COMPLETED` |
| 8 | `credit` (refunded) | `refunded` | `PAYMENT_REFUNDED` |
| 9, 16 | chargeback | `disputed` | `UNKNOWN` |
| 10 | `chargeback_accept` | `refunded` | `PAYMENT_REFUNDED` |
| 11, 12 | `error`, `declined` | `failed` | `PAYMENT_FAILED` |
| 13, 14 | `fraud` (review), `pending_auth` | `processing` | `PAYMENT_PENDING` |
| 15 | `3d_auth` (3-D Secure required) | `pending` | `PAYMENT_PENDING` |
| 17, 23 | `reversed`, `expired` | `cancelled` | `PAYMENT_FAILED` |

The IPN idempotency key is `<ntpID>:<framework status>`, so a refund IPN after
the payment IPN is not dropped as a duplicate, while `paid` (3) and `confirmed`
(5) still collapse into one completion.

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

- **IPN signature:** each IPN carries an RS512 JWT in `Verification-Token`
  (`iss` "NETOPIA Payments", `aud` = POS signature, `sub` = base64 sha512 of the
  raw body). `verify_webhook` checks all of it against the `public_key`
  credential (PEM certificate or public key; a PEM flattened onto one line is
  fine) and fails closed: no key, no token or any failed check → False. The
  algorithm is pinned to RS512, unlike the official SDKs which trust the token
  header. Needs `cryptography` (`bapp-connectors[netopia]`). The manifest's
  `signature_method="netopia-jwt"` maps to a generic verifier that always
  rejects, so a host that skips the adapter cannot accept an IPN by accident.
- **Errors come back as HTTP 200:** a refused operation answers 200 with
  `{"error": {"code": "103", ...}}`. `raise_for_netopia_error` treats `00`
  (approved), `100` (3-D Secure) and `101` (redirect) as success and raises
  `NetopiaOperationError` (permanent, not retried) for anything else.
- **Live host:** the API lives on `secure.mobilpay.ro/pay/`;
  `secure.netopia-payments.com` is the marketing site and 302s every call.
- **`healz` is unauthenticated:** it cannot tell a good key from a bad one, so
  `test_connection` queries `operation/status` for a placeholder ntpID instead.
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
