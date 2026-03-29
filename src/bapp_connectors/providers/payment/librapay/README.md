# LibraPay

Libra Internet Bank payment gateway for online card payments with HMAC-SHA1 form-based checkout and IPN verification.

- **API version:** Form-based (no REST API)
- **Base URL:** `https://secure.librapay.ro/`
- **Auth:** Custom HMAC-SHA1 signature (`merchant` + `terminal` + `key`)
- **Webhooks:** Supported (IPN POST with `P_SIGN` HMAC-SHA1 in body)
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `merchant` | Merchant ID | Yes | No |
| `terminal` | Terminal ID | Yes | No |
| `key` | Merchant Key (hex-encoded) | Yes | Yes |
| `merchant_name` | Merchant Name | Yes | No |
| `merchant_url` | Merchant URL | Yes | No |
| `merchant_email` | Merchant Email | Yes | No |

The `key` must be hex-encoded. The adapter decodes it with `binascii.unhexlify` at init
time.

## Settings

| Field | Label | Type | Default | Required |
|-------|-------|------|---------|----------|
| `sandbox` | Sandbox Mode | Boolean | `false` | No |
| `back_url` | Back URL | String | — | No |

When `sandbox` is enabled, the form action URL switches to
`https://merchant.librapay.ro/pay_auth.php` instead of the live URL.

## Capabilities

| Capability | Supported |
|------------|-----------|
| Create checkout session | Yes (form-based) |
| Get payment status | No (IPN only) |
| Refund | No (manual via back office) |
| Webhook verification (IPN) | Yes (HMAC-SHA1) |
| Webhook parsing (IPN) | Yes |

## API Endpoints

LibraPay does not have a REST API. All interaction is via form POST and IPN callbacks.

| Method | URL | Purpose |
|--------|-----|---------|
| POST (form) | `https://secure.librapay.ro/pay_auth.php` (live) | Submit payment form |
| POST (form) | `https://merchant.librapay.ro/pay_auth.php` (sandbox) | Submit payment form (test) |
| POST (IPN) | Merchant back URL | LibraPay sends payment result notification |

## Payment Flow

1. `create_checkout_session()` builds signed form data with HMAC-SHA1 hash
2. Consumer renders the form data as hidden HTML inputs, form action points to LibraPay
3. Customer submits form, is redirected to LibraPay payment page
4. After payment, LibraPay POSTs IPN notification back
5. Verify IPN with `verify_webhook()`, parse with `parse_webhook()` or `get_payment_from_ipn()`

The returned `CheckoutSession.extra` contains:
- `form_data` -- dict of all form fields (render as hidden inputs)
- `form_action` -- the form POST URL (live or sandbox depending on config)

## Payment Status Mapping

### IPN `RC` field (Response Code)

| `RC` value | Meaning | Mapped status |
|------------|---------|---------------|
| `00` | Approved | `approved` |
| Any other | Error | `error_{RC}` |

### IPN fields used for PaymentResult

| IPN Field | Mapped to |
|-----------|-----------|
| `INT_REF` (fallback `ORDER`) | `payment_id` |
| `AMOUNT` | `amount` |
| `CURRENCY` | `currency` |
| `RC` | `status` (see above) |
| `ACTION` | `extra.action` |
| `MESSAGE` | `extra.message` |
| `RRN` | `extra.rrn` |
| `APPROVAL` | `extra.approval` |

## HMAC Signature Format

LibraPay uses HMAC-SHA1 with the same length-prefixed encoding as EuPlatesc. Each value
is prefixed by its byte length; `None` or empty values are represented as `-`. The result
is uppercased.

### Checkout form fields (HMAC order)

`AMOUNT`, `CURRENCY`, `ORDER`, `DESC`, `MERCH_NAME`, `MERCH_URL`, `MERCHANT`,
`TERMINAL`, `EMAIL`, `TRTYPE`, `COUNTRY`, `MERCH_GMT`, `TIMESTAMP`, `NONCE`, `BACKREF`

### IPN verification fields (HMAC order)

`TERMINAL`, `TRTYPE`, `ORDER`, `AMOUNT`, `CURRENCY`, `DESC`, `ACTION`, `RC`, `MESSAGE`,
`RRN`, `INT_REF`, `APPROVAL`, `TIMESTAMP`, `NONCE`

## API Quirks

- **No REST API:** LibraPay is entirely form-based. There is no endpoint to query
  payment status -- results come exclusively via IPN notifications.
- **Refunds are manual:** Must be processed through the LibraPay merchant back office.
- **`get_payment()` raises `NotImplementedError`:** Since there is no status query API.
- **Uppercase field names:** All form and IPN fields use uppercase names (`AMOUNT`,
  `CURRENCY`, `ORDER`, etc.), unlike EuPlatesc which uses lowercase.
- **HMAC-SHA1 vs HMAC-MD5:** LibraPay uses SHA1 while EuPlatesc uses MD5. The signature
  field is `P_SIGN` (not `fp_hash`).
- **`TRTYPE` field:** Always set to `0` for purchase transactions.
- **`COUNTRY` and `MERCH_GMT` are `None`:** These are included in the HMAC computation
  as `-` but not sent in the form data.
- **Sandbox environment:** Has a separate URL (`merchant.librapay.ro`) unlike EuPlatesc
  where sandbox and live share the same URL.
- **Hex-encoded key:** The `key` credential must be hex-encoded; the adapter decodes it
  to raw bytes for HMAC computation.
- **IPN body format:** Can be either `application/x-www-form-urlencoded` or JSON. The
  adapter handles both.
