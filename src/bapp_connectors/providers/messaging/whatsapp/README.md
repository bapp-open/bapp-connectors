# WhatsApp

WhatsApp Business Cloud API integration for sending messages, media, templates, and interactive content.

- **API version:** v21.0 (Meta Graph API)
- **Base URL:** `https://graph.facebook.com/v21.0/`
- **Auth:** Bearer token
- **Webhooks:** Supported (HMAC-SHA256 signature via `X-Hub-Signature-256`)
- **Rate limit:** 80 req/s, burst 100

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `token` | Access Token | Yes | Yes |
| `phone_number_id` | Phone Number ID | Yes | No |

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `api_version` | API Version | str | `v21.0` | Meta Graph API version (e.g., `v21.0`). |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Send text message | Yes |
| Send bulk messages | Yes (sequential) |
| Reply to message | Yes (via `reply_to` context threading) |
| Receive messages (inbound) | Yes (via webhook) |
| Webhooks | Yes (`messages`, `message_status`) |
| Send template message | Yes (via `OutboundMessage.template_id`) |
| Send image | Yes (via `extra.media_type="image"`) |
| Send document | Yes (via `extra.media_type="document"`) |
| Send video | Yes (via `extra.media_type="video"`) |
| Send audio | Yes (via `extra.media_type="audio"`) |
| Send sticker | Yes (via `extra.media_type="sticker"`) |
| Send location | Yes (client only) |
| Send interactive message | Yes (client only) |
| Send contacts | Yes (client only) |
| Send reaction | Yes (client only) |
| Mark as read | Yes (client only) |
| Media management | Yes (get URL / delete, client only) |
| Raw payload passthrough | Yes (via `extra.raw_payload`) |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `{phone_number_id}` | Verify credentials (connection test) |
| POST | `{phone_number_id}/messages` | Send any message type |
| GET | `{media_id}` | Get media download URL |
| DELETE | `{media_id}` | Delete a media object |

## Template Messages

WhatsApp requires pre-approved templates for initiating conversations. Set
`OutboundMessage.template_id` to the template name and use `template_vars` for
dynamic components:

```python
OutboundMessage(
    to="5511999999999",
    body="",
    template_id="order_confirmation",
    template_vars={
        "components": [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "Order #1234"},
                ],
            }
        ]
    },
    extra={"language": "pt_BR"},
)
```

## Sending Media Messages

Set `OutboundMessage.extra` fields to send media instead of text:

```python
OutboundMessage(
    to="5511999999999",
    body="",
    extra={
        "media_type": "image",         # image | document | video | audio | sticker
        "media_url": "https://...",    # or use "media_id" for uploaded media
        "caption": "Optional caption",
        "filename": "report.pdf",      # for documents
    },
)
```

## API Quirks

- **Single messages endpoint:** All message types (text, template, media,
  interactive, location, contacts, reactions) are sent via the same
  `POST /{phone_number_id}/messages` endpoint with different payload structures.
- **Template-first conversations:** WhatsApp requires using a pre-approved
  template message to initiate a conversation. Free-form text messages can only
  be sent within a 24-hour window after the user last messaged.
- **Message ID format:** WhatsApp returns message IDs in `wamid.{...}` format.
  These are extracted from the `messages[0].id` field in the response.
- **Reply context:** Reply threading uses a `context.message_id` field in the
  payload, not `reply_parameters` like Telegram.
- **No batch API:** The Cloud API does not support batch/bulk sending. The
  `send_bulk` method sends messages sequentially.
- **API version in URL:** The Graph API version is embedded in the base URL path.
  Changing the `api_version` setting rebuilds the base URL at adapter
  initialization.
- **Webhook signature:** Webhooks are validated using HMAC-SHA256 via the
  `X-Hub-Signature-256` header, consistent with Meta's webhook verification
  pattern across Facebook and Instagram APIs.
- **Media via URL or ID:** Media can be sent by providing a public URL
  (`media_url`) or a previously uploaded media ID (`media_id`). The client
  methods accept an `is_media_id` boolean to toggle between them.
