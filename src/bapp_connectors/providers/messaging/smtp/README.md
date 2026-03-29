# SMTP Email

SMTP email integration for sending email messages via any standard SMTP server.

- **API version:** SMTP protocol (RFC 5321)
- **Base URL:** `smtp://{host}:{port}`
- **Auth:** SMTP login (`username` + `password`)
- **Webhooks:** Not supported
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive | Default |
|-------|-------|----------|-----------|---------|
| `host` | SMTP Host | Yes | No | |
| `port` | SMTP Port | Yes | No | `587` |
| `username` | Username | Yes | No | |
| `password` | Password | Yes | Yes | |
| `from_email` | From Email | No | No | _(defaults to username)_ |
| `use_tls` | Use TLS | No | No | `true` |
| `use_ssl` | Use SSL | No | No | `false` |
| `timeout` | Timeout (seconds) | No | No | `30` |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Send single email | Yes |
| Send bulk email | Yes (sequential) |
| Reply to message | Yes (inherited from MessagingPort) |
| Receive messages (inbound) | No |
| Webhooks | No |
| Plain text body | Yes |
| HTML body | Yes |
| CC / BCC recipients | Yes (via `extra.cc`, `extra.bcc`) |
| File attachments | Yes (via `message.attachments`) |
| Custom from address per-message | Yes (via `extra.from_email`) |

## API Quirks

- **Not HTTP-based:** This provider uses Python's `smtplib` directly, not the
  `ResilientHttpClient`. The `http_client` parameter is accepted for interface
  compatibility but is not used.
- **Host auto-detection:** If `host` is not provided but `username` contains an
  `@` sign, the host is derived from the domain part of the username.
- **TLS vs SSL:** `use_tls` enables STARTTLS on a plain connection (typical for
  port 587). `use_ssl` creates an `SMTP_SSL` connection from the start (typical
  for port 465). Do not enable both simultaneously.
- **Connection per send:** Each `send()` call opens a new SMTP connection, sends
  the email, and closes the connection. There is no connection pooling.
- **Attachment format:** Attachments are passed via `OutboundMessage.attachments`
  as a list of dicts with keys: `filename`, `content` (bytes), and `content_type`.
- **Subject and HTML:** The adapter reads `OutboundMessage.subject` for the email
  subject and `OutboundMessage.html_body` for HTML content. Both are first-class
  fields on the DTO, not buried in `extra`.
- **No delivery tracking:** SMTP does not provide message IDs or delivery receipts.
  The `DeliveryReport.message_id` is carried over from the `OutboundMessage`.
- **Multipart format:** Emails are always sent as `multipart/alternative`. If both
  plain text and HTML bodies are provided, both are included.
