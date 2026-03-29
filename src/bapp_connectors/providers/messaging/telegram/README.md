# Telegram

Telegram Bot API integration for sending messages, media, stickers, locations, and interactive content.

- **API version:** Telegram Bot API
- **Base URL:** `https://api.telegram.org/bot{token}/`
- **Auth:** Bot token embedded in URL path
- **Webhooks:** Supported (signature header: `X-Telegram-Bot-Api-Secret-Token`)
- **Rate limit:** 30 req/s, burst 50

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `bot_token` | Bot Token | Yes | Yes |

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `parse_mode` | Default Parse Mode | select | `HTML` | Default formatting for message text. Choices: `HTML`, `Markdown`, `MarkdownV2`. |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Send text message | Yes |
| Send bulk messages | Yes (sequential) |
| Reply to message | Yes (via `reply_to` threading) |
| Receive messages (inbound) | Yes (via webhook) |
| Webhooks | Yes (`message`, `callback_query`, `edited_message`) |
| Send photo | Yes (via `extra.media_type="photo"`) |
| Send document | Yes (via `extra.media_type="document"`) |
| Send video | Yes (via `extra.media_type="video"`) |
| Send audio | Yes (via `extra.media_type="audio"`) |
| Send voice | Yes (via `extra.media_type="voice"`) |
| Send sticker | Yes (via `extra.media_type="sticker"`) |
| Send animation/GIF | Yes (via `extra.media_type="animation"`) |
| Send location | Yes (client only) |
| Send contact | Yes (client only) |
| Inline keyboards | Yes (via `extra.reply_markup`) |
| Edit message | Yes (client only) |
| Delete message | Yes (client only) |
| Forward message | Yes (client only) |
| Raw API passthrough | Yes (via `extra.raw_method` + `extra.raw_payload`) |
| Webhook management | Yes (set/delete/info via client) |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `getMe` | Verify bot token and get bot info |
| POST | `sendMessage` | Send a text message |
| POST | `sendPhoto` | Send a photo |
| POST | `sendDocument` | Send a document |
| POST | `sendVideo` | Send a video |
| POST | `sendAudio` | Send an audio file |
| POST | `sendVoice` | Send a voice message |
| POST | `sendSticker` | Send a sticker |
| POST | `sendAnimation` | Send a GIF/animation |
| POST | `sendLocation` | Send a location |
| POST | `sendContact` | Send a contact card |
| POST | `editMessageText` | Edit an existing message |
| POST | `deleteMessage` | Delete a message (< 48h old) |
| POST | `forwardMessage` | Forward a message from another chat |
| POST | `setWebhook` | Register a webhook URL |
| POST | `deleteWebhook` | Remove the webhook |
| POST | `getWebhookInfo` | Get current webhook status |

## Inbound Message Mapping

The `inbound_message_from_telegram` mapper handles `message`, `edited_message`, and
`channel_post` update types. Non-message updates (e.g. `callback_query`) return `None`.

Detected message types: `text`, `photo`, `document`, `video`, `audio`, `voice`,
`sticker`, `animation`, `location`, `contact`.

## Sending Media Messages

Set `OutboundMessage.extra` fields to send media instead of text:

```python
OutboundMessage(
    to="chat_id",
    body="",  # or caption text
    extra={
        "media_type": "photo",       # photo | document | video | audio | voice | sticker | animation
        "media_url": "https://...",  # or use "media_id" for Telegram file_id
        "caption": "Optional caption",
        "parse_mode": "HTML",        # optional override
    },
)
```

## API Quirks

- **Auth via URL path:** The bot token is embedded in the base URL
  (`/bot{token}/`), not sent as a header. The adapter uses `NoAuth` for the
  HTTP client.
- **All methods are POST:** Every Telegram Bot API method uses POST with a JSON
  body, even read-only operations like `getMe`.
- **Response unwrapping:** All API responses are wrapped in `{"ok": true, "result": ...}`.
  The client automatically extracts the `result` field.
- **No batch API:** Telegram does not support batch/bulk message sending. The
  `send_bulk` method sends messages sequentially.
- **Sticker captions:** Stickers do not support captions. The mapper skips the
  caption field when `media_type="sticker"`.
- **Reply parameters:** Replies use the `reply_parameters` object with
  `allow_sending_without_reply: true` to avoid errors if the original message
  was deleted.
- **Delete message limit:** Messages can only be deleted within 48 hours of
  being sent.
