# RoboSMS

RoboSMS integration for sending SMS messages via the RoboSMS cloud API.

- **API version:** v1
- **Base URL:** `https://robo-sms.com/api/`
- **Auth:** Token header (`Token {token}`)
- **Webhooks:** Not supported
- **Rate limit:** 5 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `token` | API Token | Yes | Yes |
| `device_id` | Device ID | No | No |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Send single SMS | Yes |
| Send bulk SMS | Yes (sequential) |
| Reply to message | Yes (inherited from MessagingPort) |
| Receive messages (inbound) | No |
| Webhooks | No |
| Delivery status tracking | Partial (sent/failed only) |
| Per-message device override | Yes (via `extra.device_id`) |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `sms/` | Send a single SMS message |

## API Quirks

- **Connection test sends to invalid number:** `test_auth()` sends a dummy SMS to
  `"00"` and checks if a 400 error is returned. A 400 means auth succeeded but the
  request was invalid (expected behavior for the test).
- **Device ID is optional:** If `device_id` is not provided in credentials, it can
  be overridden per-message via `OutboundMessage.extra["device_id"]`.
- **Response message ID:** The adapter extracts the `id` field from the JSON
  response and uses it as the `DeliveryReport.message_id`. Falls back to the
  original `OutboundMessage.message_id` if not present.
- **No bulk endpoint:** Bulk sends are performed sequentially, one message at a time.
