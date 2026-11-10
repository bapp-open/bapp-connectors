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
| `from_name` | From Name | No | No | _(address only)_ |
| `use_tls` | Use TLS | No | No | `true` |
| `use_ssl` | Use SSL | No | No | `false` |
| `timeout` | Timeout (seconds) | No | No | `30` |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Send single email | Yes |
| Send bulk email | Yes (sequential) |
| Reply to message | Yes (`reply_to` RFC ID + `extra.references`) |
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
- **MIME structure:** A single body uses `text/plain` or `text/html`; both use
  `multipart/alternative` with plain text first. Attachments use an outer
  `multipart/mixed`, containing the body (including a nested alternative when
  both variants exist) followed by attachments. Attachment-only messages are
  supported. Each attachment keeps its MIME `content_type` (including parameters),
  bytes and `filename`; Unicode names use standard MIME header encoding.

## Message identifiers and replies

`OutboundMessage.message_id` remains the caller's correlation identifier. It can
be an internal database ID or UUID and is **not** copied to the RFC `Message-ID`
header, even if it happens to look like an RFC ID. This preserves the existing
email adapter/report contract. No existing outbound References field is defined
on the DTO; the SMTP options below live in `extra` without changing DTO fields.

- Every SMTP submission receives an RFC `Message-ID`, generated with Python's
  `email.utils.make_msgid()` unless `extra["rfc_message_id"]` explicitly supplies
  one, for example `<outgoing-123@example.test>`.
- `DeliveryReport.message_id` preserves a nonempty caller correlation ID. If it
  was empty, the report uses the assigned RFC ID instead. In both cases,
  `DeliveryReport.extra["rfc_message_id"]` identifies the exact header serialized
  for submission. On failure it is the assigned ID, not evidence of acceptance;
  an invalid explicit RFC ID fails validation before any ID is assigned.
- `OutboundMessage.reply_to` is the quoted message's RFC `Message-ID`, sent as
  `In-Reply-To`. Use `EmailDetail.headers["Message-ID"]`, **not**
  `EmailDetail.message_id` (which is an IMAP UID).
- Supply the parent's `EmailDetail.references` in `extra["references"]`. Both a
  list of bracketed RFC IDs and a space-separated string are accepted. The order
  is preserved, and the parent ID is appended unless already last. Without a
  supplied chain, a reply's `References` contains just the parent ID.
- The optional `extra["reply_to"]` is a separate email address for the RFC
  `Reply-To` header, consistent with the other email providers. It never uses
  `OutboundMessage.reply_to` as an address.
- RFC IDs must be single, bracketed ASCII message identifiers. Invalid IDs,
  malformed reference chains and attachment content types fail before connecting.
  Header inputs (including names, filenames and envelope addresses) reject control
  characters, including CR/LF, to prevent header injection. Pass References as
  parsed IDs, without raw header folding/newlines.

Example, using an already fetched parent message:

```python
from bapp_connectors.core.dto import OutboundMessage

report = adapter.send(OutboundMessage(
    channel="email",
    message_id="local-outbox-123",  # caller correlation ID, unchanged in the report
    to=parent.sender.address,
    subject="Re: " + parent.subject,
    body="Thank you for your order.",
    reply_to=parent.headers.get("Message-ID", ""),
    extra={
        "references": parent.references,
        "from_email": "comenzi@example.test",
    },
))
# Store report.extra["rfc_message_id"] for subsequent threading and SMTP log lookup.
```

`SMTPClient.send_email()` still returns a `bool` and keeps its existing positional
arguments. The new `message_id`, `in_reply_to`, `references` and `reply_to` arguments
are keyword-only; at this low level, `message_id` explicitly means the RFC ID.

## Sender aliases

Authentication always uses credentials `username` and `password`. Sender selection
is independent: a nonempty `message.extra["from_email"]` overrides credentials
`from_email`, which falls back to `username`. That address is used both in the
`From` header and the SMTP envelope sender (`MAIL FROM`). A nonempty
`extra["from_name"]` similarly overrides credentials `from_name`; empty overrides
retain the credential default. These sender defaults come from **credentials**,
not the adapter's `config` argument, preserving existing behavior.

For example, `username=john.doe@example.test` and
`from_email=comenzi@example.test` authenticate as John Doe and send as Comenzi.
The SMTP server must authorize that account to send with the alias; it can reject
an unauthorized sender. Selecting an alias automatically from the recipient of an
inbound email belongs to the calling application.

## Submission results

`SENT` means the SMTP server accepted the message for all envelope recipients.
It does **not** confirm recipient delivery, inbox placement or reading;
`delivered_at` stays unset. MIME/threading fixes alone do not establish the cause
of a missing email. Use the RFC ID to correlate SMTP/server logs and any later
bounce when investigating delivery.

Connection/authentication errors, sender/data rejections and recipient refusals
produce `FAILED` with an error, preserving existing exception reporting.
Recipient refusals also expose `extra["refused_recipients"]`, keyed by address,
with SMTP `code` and decoded `message`. A partial refusal also produces `FAILED`:
other recipients may already have been accepted, so retrying the entire message
may send duplicates. A successful submission is not changed to failure solely
because the subsequent `QUIT` fails.

## Regression tests

```bash
uv run --extra dev pytest tests/email/smtp/ -v -p no:django
```

The default pytest configuration excludes integration tests. Regression tests
mock the SMTP transport and inspect serialized MIME and delivery reports; they
send no real emails.
