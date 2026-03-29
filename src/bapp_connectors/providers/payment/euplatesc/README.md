# EuPlatesc

Romanian payment gateway for online card payments with HMAC-MD5 form-based checkout and IPN verification.

- **API version:** Form-based (no REST API)
- **Base URL:** `https://secure.euplatesc.ro/`
- **Auth:** Custom HMAC-MD5 signature (`merchant_id` + `merchant_key`)
- **Webhooks:** Supported (IPN POST with `fp_hash` HMAC-MD5 in body)
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `merchant_id` | Merchant ID | Yes | No |
| `merchant_key` | Merchant Key | Yes | Yes |

The `merchant_key` must be hex-encoded. The adapter decodes it with `binascii.unhexlify`
at init time.

## Settings

| Field | Label | Type | Default | Required |
|-------|-------|------|---------|----------|
| `default_currency` | Default Currency | Select (`RON`, `EUR`, `USD`) | `RON` | No |
| `notify_url` | IPN Notification URL | String | — | No |
| `back_url` | Back URL | String | — | No |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Create checkout session | Yes (form-based) |
| Get payment status | No (IPN only) |
| Refund | No (manual via back office) |
| Webhook verification (IPN) | Yes (HMAC-MD5) |
| Webhook parsing (IPN) | Yes |

## API Endpoints

EuPlatesc does not have a REST API. All interaction is via form POST and IPN callbacks.

| Method | URL | Purpose |
|--------|-----|---------|
| POST (form) | `https://secure.euplatesc.ro/tdsprocess/tranzactd.php` | Submit payment form (customer redirect) |
| POST (IPN) | Merchant `notify_url` | EuPlatesc sends payment result notification |

## Payment Flow

1. `create_checkout_session()` builds signed form data with HMAC-MD5 hash
2. Consumer renders the form data as hidden HTML inputs, form action points to EuPlatesc
3. Customer submits form, is redirected to EuPlatesc payment page
4. After payment, EuPlatesc POSTs IPN notification to `notify_url`
5. Verify IPN with `verify_webhook()`, parse with `parse_webhook()` or `get_payment_from_ipn()`

The returned `CheckoutSession.extra` contains:
- `form_data` -- dict of all form fields (render as hidden inputs)
- `form_action` -- the form POST URL

## Payment Status Mapping

### IPN `action` field

| `action` value | Meaning | Mapped status |
|----------------|---------|---------------|
| `0` | Approved | `approved` |
| Any other | Error | `error_{action}` |

### IPN `sec_status` field (3-D Secure)

| `sec_status` | Meaning |
|--------------|---------|
| `1` | Valid, not finished |
| `2` | Failed |
| `3` | Manual verification |
| `4` | Waiting response |
| `5` | Possible fraud |
| `6` | Shipping not allowed |
| `7` | Pickup in store |
| `8` | Authenticated OK |
| `9` | Verified OK |

If `action=0` but `sec_status` is not `8` or `9`, the payment is marked as `suspect`.

## HMAC Signature Format

EuPlatesc uses a custom HMAC-MD5 encoding where each value is prefixed by its byte
length. Empty values are represented as `-`. The fields are concatenated in a fixed
order and then signed with the merchant key.

### Checkout form fields (HMAC order)

`amount`, `curr`, `invoice_id`, `order_desc`, `merch_id`, `timestamp`, `nonce`

### IPN verification fields (HMAC order)

`amount`, `curr`, `invoice_id`, `ep_id`, `merch_id`, `action`, `message`, `approval`,
`timestamp`, `nonce` (+ optional `sec_status`)

## API Quirks

- **No REST API:** EuPlatesc is entirely form-based. There is no endpoint to query
  payment status -- results come exclusively via IPN notifications.
- **Refunds are manual:** Must be processed through the EuPlatesc merchant back office
  at `secure.euplatesc.ro`.
- **`get_payment()` raises `NotImplementedError`:** Since there is no status query API.
- **IPN body format:** Can be either `application/x-www-form-urlencoded` or JSON. The
  adapter handles both.
- **Signature in body, not header:** Unlike most webhooks, the HMAC hash (`fp_hash`) is
  included in the POST body, not in an HTTP header.
- **Sandbox URL is the same as live:** Both point to
  `https://secure.euplatesc.ro/tdsprocess/tranzactd.php`.
- **Hex-encoded key:** The `merchant_key` credential must be hex-encoded; the adapter
  decodes it to raw bytes for HMAC computation.
