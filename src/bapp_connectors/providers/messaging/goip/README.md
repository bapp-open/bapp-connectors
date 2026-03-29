# GoIP

GoIP GSM gateway for sending SMS via a physical device over HTTP.

- **API version:** Custom HTTP interface
- **Base URL:** `http://{device_ip}/default/en_US/`
- **Auth:** HTTP Basic (`username` + `password`)
- **Webhooks:** Not supported
- **Rate limit:** 1 req/s, burst 3

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `username` | Username | Yes | No |
| `password` | Password | Yes | Yes |
| `ip` | Device IP | Yes | No |

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `line` | SIM Line | int | `1` | GSM line/SIM slot to use for sending. |
| `max_retries` | Max Retries | int | `0` | Number of retries when the line is busy. |
| `base_url` | Custom Base URL | str | _(auto)_ | Override the auto-generated base URL (`http://{ip}/default/en_US/`). |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Send single SMS | Yes |
| Send bulk SMS | Yes (sequential) |
| Reply to message | Yes (inherited from MessagingPort) |
| Receive messages (inbound) | No |
| Webhooks | No |
| Delivery status tracking | Partial (sent/failed only) |
| Per-message SIM line override | Yes (via `extra.line`) |
| Device status check | Yes (client only) |
| Clear SMS history | Yes (client only) |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `send.html?n={to}&m={message}&l={line}&u={user}&p={pass}` | Send an SMS |
| GET | `status.html` | Device status (used for connection test) |
| GET | `send_status.xml` | Send queue status |
| GET | `tools.html?action=del&type=sms_inbox&line={line}&pos=-1` | Clear received SMS history |
| GET | `tools.html?action=del&type=sms_outbox&line={line}&pos=-1` | Clear sent SMS history |

## API Quirks

- **All GET requests:** The GoIP device uses GET for every operation, including
  sending SMS. Credentials are passed as query parameters, not headers.
- **Auth via query params:** Despite the manifest declaring `BASIC` auth strategy,
  the actual send endpoint requires `u` and `p` query parameters rather than an
  `Authorization` header. Basic auth is used for the web interface status pages.
- **Message length limit:** Messages must be under 3000 characters.
- **Busy line retry:** When the GSM line is busy, the client retries with a 1-second
  delay up to `max_retries` times. If still busy, returns a `FAILED` delivery report
  rather than raising an exception.
- **Base URL construction:** The base URL is dynamically built from the `ip`
  credential (`http://{ip}/default/en_US/`) unless overridden via the `base_url`
  setting.
- **No message IDs:** The device does not return a message ID on send. The
  `DeliveryReport.message_id` is carried over from the `OutboundMessage`.
- **Physical device:** This is a hardware GSM gateway, not a cloud API. Network
  connectivity to the device's local IP is required.
