"""
Telegram <-> DTO mappers.

Converts between raw Telegram Bot API payloads and normalized framework DTOs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    InboundMessage,
    MessageChannel,
    OutboundMessage,
    ProviderMeta,
)

# ── Delivery report ──


def delivery_report_from_telegram(response: dict, original_message_id: str = "") -> DeliveryReport:
    """Map a Telegram send response (the 'result' Message object) to a DeliveryReport."""
    tg_message_id = str(response.get("message_id", ""))
    chat = response.get("chat", {})
    return DeliveryReport(
        message_id=tg_message_id or original_message_id,
        status=DeliveryStatus.SENT,
        extra={
            "tg_message_id": tg_message_id,
            "chat_id": chat.get("id"),
            "chat_type": chat.get("type", ""),
        },
    )


# ── Inbound message (from webhook) ──


def inbound_message_from_telegram(update: dict) -> InboundMessage | None:
    """Parse a Telegram webhook Update into an InboundMessage DTO.

    Handles: message, edited_message, channel_post.
    Returns None for non-message updates (callback_query, etc.).
    """
    msg = update.get("message") or update.get("edited_message") or update.get("channel_post")
    if not msg:
        return None

    sender = msg.get("from", {})
    chat = msg.get("chat", {})

    # Extract text from various message types
    body = msg.get("text", "")
    if not body:
        body = msg.get("caption", "")

    timestamp = None
    if ts := msg.get("date"):
        timestamp = datetime.fromtimestamp(ts, tz=UTC)

    return InboundMessage(
        message_id=str(msg.get("message_id", "")),
        channel=MessageChannel.OTHER,
        sender=str(chat.get("id", sender.get("id", ""))),
        body=body,
        received_at=timestamp,
        extra={
            "update_id": update.get("update_id"),
            "from": sender,
            "chat": chat,
            "message_type": _detect_message_type(msg),
            "raw_message": msg,
        },
        provider_meta=ProviderMeta(
            provider="telegram",
            raw_id=str(msg.get("message_id", "")),
            raw_payload=update,
            fetched_at=datetime.now(UTC),
        ),
    )


def _detect_message_type(msg: dict) -> str:
    """Detect the Telegram message type from the message object."""
    for msg_type in ("text", "photo", "document", "video", "audio", "voice", "sticker", "animation", "location", "contact"):
        if msg_type in msg:
            return msg_type
    return "unknown"


# ── Outbound payload builders ──


def _reply_params(reply_to: str) -> dict | None:
    """Build Telegram reply_parameters from a message ID."""
    if reply_to:
        try:
            return {"message_id": int(reply_to), "allow_sending_without_reply": True}
        except (ValueError, TypeError):
            return None
    return None


def build_text_payload(message: OutboundMessage, parse_mode: str = "HTML") -> dict:
    """Build a Telegram sendMessage payload."""
    payload: dict = {
        "chat_id": message.to,
        "text": message.body,
        "parse_mode": message.extra.get("parse_mode", parse_mode) if message.extra else parse_mode,
    }
    if rp := _reply_params(message.reply_to):
        payload["reply_parameters"] = rp
    if message.extra:
        if markup := message.extra.get("reply_markup"):
            payload["reply_markup"] = markup
    return payload


def build_media_payload(message: OutboundMessage, parse_mode: str = "HTML") -> tuple[str, dict] | None:
    """Build a Telegram media send payload.

    Returns (api_method, payload) or None if not a media message.

    Supports via message.extra:
      - extra.media_type: "photo" | "document" | "video" | "audio" | "voice" | "sticker" | "animation"
      - extra.media_url or extra.media_id: the media source
      - extra.caption: optional caption
    """
    if not message.extra:
        return None

    media_type = message.extra.get("media_type")
    method_map = {
        "photo": "sendPhoto",
        "document": "sendDocument",
        "video": "sendVideo",
        "audio": "sendAudio",
        "voice": "sendVoice",
        "sticker": "sendSticker",
        "animation": "sendAnimation",
    }
    api_method = method_map.get(media_type)
    if not api_method:
        return None

    media_value = message.extra.get("media_id") or message.extra.get("media_url")
    if not media_value:
        return None

    payload: dict = {
        "chat_id": message.to,
        media_type: media_value,
    }

    # Stickers don't support captions
    if media_type != "sticker":
        caption = message.extra.get("caption", message.body)
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = message.extra.get("parse_mode", parse_mode)

    if rp := _reply_params(message.reply_to):
        payload["reply_parameters"] = rp

    return api_method, payload


def build_location_payload(message: OutboundMessage) -> tuple[str, dict] | None:
    """Build a Telegram sendLocation or sendVenue payload from extra.location."""
    if not message.extra:
        return None
    loc = message.extra.get("location")
    if not loc:
        return None

    payload: dict = {
        "chat_id": message.to,
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
    }
    if rp := _reply_params(message.reply_to):
        payload["reply_parameters"] = rp

    # If name/address provided, use sendVenue
    if loc.get("name") or loc.get("address"):
        payload["title"] = loc.get("name", "")
        payload["address"] = loc.get("address", "")
        return "sendVenue", payload

    return "sendLocation", payload


def build_contact_payload(message: OutboundMessage) -> tuple[str, dict] | None:
    """Build a Telegram sendContact payload from extra.contact."""
    if not message.extra:
        return None
    contact = message.extra.get("contact")
    if not contact:
        return None

    name = contact.get("name", "")
    parts = name.split(" ", 1)

    payload: dict = {
        "chat_id": message.to,
        "phone_number": contact.get("phone", ""),
        "first_name": parts[0],
    }
    if len(parts) > 1:
        payload["last_name"] = parts[1]
    if rp := _reply_params(message.reply_to):
        payload["reply_parameters"] = rp

    return "sendContact", payload


def build_payload(message: OutboundMessage, default_parse_mode: str = "HTML") -> tuple[str, dict]:
    """Build the appropriate Telegram API method + payload.

    Returns (api_method, payload).
    """
    # Media message
    if message.extra and message.extra.get("media_type"):
        result = build_media_payload(message, default_parse_mode)
        if result:
            return result

    # Location / venue
    if message.extra and message.extra.get("location"):
        result = build_location_payload(message)
        if result:
            return result

    # Contact
    if message.extra and message.extra.get("contact"):
        result = build_contact_payload(message)
        if result:
            return result

    # Default: text
    return "sendMessage", build_text_payload(message, default_parse_mode)
