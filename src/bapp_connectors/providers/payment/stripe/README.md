# Stripe

Global payment processing platform supporting checkout sessions, payment intents, refunds, and webhook notifications.

- **API version:** v1 (REST)
- **Base URL:** `https://api.stripe.com/v1/`
- **Auth:** Bearer token (`secret_key`)
- **Webhooks:** Supported (HMAC-SHA256 via `Stripe-Signature` header)
- **Rate limit:** 25 req/s, burst 50

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `secret_key` | Secret Key | Yes | Yes |

The secret key follows the format `sk_live_...` (production) or `sk_test_...` (test mode).

For webhook verification, an optional `webhook_secret` can be provided in the credentials
dict (starts with `whsec_...`). This is used by `verify_webhook()` and can also be
passed directly via the `secret` parameter.

## Capabilities

| Capability | Supported |
|------------|-----------|
| Create checkout session | Yes |
| Get payment status | Yes |
| Refund (full and partial) | Yes |
| Webhook verification | Yes (HMAC-SHA256) |
| Webhook parsing | Yes |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `balance` | Test connection / verify credentials |
| POST | `checkout/sessions` | Create a checkout session |
| GET | `payment_intents/{id}` | Get payment intent status |
| POST | `refunds` | Create a refund |

## Payment Flow

1. `create_checkout_session()` creates a Stripe Checkout Session via the API
2. Stripe returns a `url` where the customer should be redirected
3. Customer completes payment on Stripe's hosted checkout page
4. Stripe sends webhook events to your endpoint
5. Verify signature with `verify_webhook()`, parse with `parse_webhook()`
6. Query status anytime with `get_payment(payment_intent_id)`

The returned `CheckoutSession.extra` contains:
- `payment_intent` -- the Stripe PaymentIntent ID
- `status` -- checkout session status
- `customer_email` -- customer email if provided

## Payment Status Mapping

### Stripe PaymentIntent status

| Stripe Status | Framework Status |
|---------------|------------------|
| `requires_payment_method` | `pending` |
| `requires_confirmation` | `pending` |
| `requires_action` | `pending` |
| `processing` | `processing` |
| `requires_capture` | `authorized` |
| `canceled` | `cancelled` |
| `succeeded` | `completed` |

### Payment method mapping

| Stripe Method | Framework PaymentMethodType |
|---------------|----------------------------|
| `card` | `CARD` |
| `bank_transfer` | `BANK_TRANSFER` |
| `sepa_debit` | `BANK_TRANSFER` |
| Other | `OTHER` |

### Webhook event mapping

| Stripe Event | Framework WebhookEventType |
|--------------|----------------------------|
| `checkout.session.completed` | `PAYMENT_COMPLETED` |
| `payment_intent.succeeded` | `PAYMENT_COMPLETED` |
| `payment_intent.payment_failed` | `PAYMENT_FAILED` |
| `charge.refunded` | `PAYMENT_REFUNDED` |

## Amount Handling

Stripe uses the **smallest currency unit** (e.g., cents for USD/EUR). The adapter
handles conversion automatically:

- `amount_to_stripe(Decimal, currency)` -- converts to integer cents
- `amount_from_stripe(int, currency)` -- converts back to Decimal

Zero-decimal currencies (JPY, KRW, VND, etc.) are handled correctly -- no multiplication
or division by 100.

### Zero-decimal currencies

BIF, CLP, DJF, GNF, JPY, KMF, KRW, MGA, PYG, RWF, UGX, VND, VUV, XAF, XOF, XPF

## Webhook Signature Verification

Stripe webhook signatures use the format: `t=timestamp,v1=signature`

The verification process:
1. Parse `Stripe-Signature` header to extract `t` (timestamp) and `v1` (signature)
2. Check timestamp tolerance (rejects events older than 5 minutes)
3. Compute HMAC-SHA256 of `"{timestamp}.{body}"` using the webhook secret
4. Compare computed signature against `v1` using constant-time comparison

## Refunds

Stripe is the only payment provider in this family that supports programmatic refunds.

- **Full refund:** `refund(payment_intent_id)` -- refunds the entire amount
- **Partial refund:** `refund(payment_intent_id, amount=Decimal("10.00"))` -- refunds
  the specified amount

For partial refunds, the adapter fetches the PaymentIntent first to determine the
currency for amount conversion.

## API Quirks

- **Form-encoded POST bodies:** Stripe's API accepts `application/x-www-form-urlencoded`
  for POST requests, not JSON. Nested parameters use bracket notation
  (e.g., `line_items[0][price_data][currency]`).
- **Bearer auth override:** When the registry provides an `http_client`, the adapter
  overrides its auth to `BearerAuth` since `CUSTOM` auth strategy means `NoAuth` by
  default from the registry.
- **No settings config:** Unlike other payment providers, Stripe has no configurable
  settings fields. All configuration is done via the secret key and webhook secret.
- **Test mode via key prefix:** Sandbox/live is determined by the key prefix
  (`sk_test_...` vs `sk_live_...`), not by a separate setting.
- **`test_connection()` fetches balance:** The client calls `GET /v1/balance` to verify
  that credentials are valid.
- **Checkout session expiry:** Stripe checkout sessions have an `expires_at` timestamp
  that is mapped to `CheckoutSession.expires_at`.
- **Partial refund requires extra call:** When refunding a partial amount, the adapter
  first fetches the PaymentIntent to determine the currency needed for amount conversion
  to the smallest unit.
