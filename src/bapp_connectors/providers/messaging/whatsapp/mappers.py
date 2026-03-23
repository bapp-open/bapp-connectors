"""
WhatsApp <-> DTO mappers.

Converts between raw WhatsApp Cloud API payloads and normalized framework DTOs.
"""

from __future__ import annotations

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    MessageChannel,
    OutboundMessage,
)


def _extract_message_id(response: dict) -> str:
    """Extract the WhatsApp message ID (wamid) from an API response."""
    messages = response.get("messages", [])
    if messages and isinstance(messages[0], dict):
        return messages[0].get("id", "")
    return ""


def delivery_report_from_whatsapp(response: dict, original_message_id: str = "") -> DeliveryReport:
    """Map a WhatsApp send response to a DeliveryReport DTO."""
    wa_message_id = _extract_message_id(response)
    return DeliveryReport(
        message_id=wa_message_id or original_message_id,
        status=DeliveryStatus.SENT,
        extra={
            "wa_message_id": wa_message_id,
            "contacts": response.get("contacts", []),
        },
    )


def build_text_payload(message: OutboundMessage) -> dict:
    """Build a WhatsApp text message payload from an OutboundMessage DTO."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": message.to,
        "type": "text",
        "text": {
            "preview_url": message.extra.get("preview_url", True) if message.extra else True,
            "body": message.body,
        },
    }


def build_template_payload(message: OutboundMessage) -> dict:
    """Build a WhatsApp template message payload from an OutboundMessage DTO."""
    payload: dict = {
        "messaging_product": "whatsapp",
        "to": message.to,
        "type": "template",
        "template": {
            "name": message.template_id,
            "language": {"code": message.extra.get("language", "en_US") if message.extra else "en_US"},
        },
    }
    if message.template_vars:
        components = message.template_vars.get("components", [])
        if components:
            payload["template"]["components"] = components
    return payload


def build_media_payload(message: OutboundMessage) -> dict | None:
    """Build a WhatsApp media message payload from an OutboundMessage DTO.

    Supports image, document, video, audio via message.extra:
      - extra.media_type: "image" | "document" | "video" | "audio"
      - extra.media_url or extra.media_id: the media source
      - extra.caption, extra.filename: optional
    """
    if not message.extra:
        return None

    media_type = message.extra.get("media_type")
    if media_type not in ("image", "document", "video", "audio", "sticker"):
        return None

    media_data: dict = {}
    if media_id := message.extra.get("media_id"):
        media_data["id"] = media_id
    elif media_url := message.extra.get("media_url"):
        media_data["link"] = media_url
    else:
        return None

    if caption := message.extra.get("caption"):
        media_data["caption"] = caption
    if filename := message.extra.get("filename"):
        media_data["filename"] = filename

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": message.to,
        "type": media_type,
        media_type: media_data,
    }


def _apply_reply_context(payload: dict, reply_to: str) -> dict:
    """Add WhatsApp context (reply threading) to a payload if reply_to is set."""
    if reply_to:
        payload["context"] = {"message_id": reply_to}
    return payload


def build_payload(message: OutboundMessage) -> dict:
    """Build the appropriate WhatsApp payload based on the message content."""
    # Template message
    if message.template_id:
        payload = build_template_payload(message)
    # Media message
    elif message.extra and message.extra.get("media_type"):
        payload = build_media_payload(message)
        if payload is None:
            payload = build_text_payload(message)
    # Default: text message
    else:
        payload = build_text_payload(message)

    return _apply_reply_context(payload, message.reply_to)
