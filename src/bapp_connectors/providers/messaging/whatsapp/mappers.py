"""
WhatsApp <-> DTO mappers.

Converts between raw WhatsApp Cloud API payloads and normalized framework DTOs.
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
    WebhookEvent,
    WebhookEventType,
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


def build_location_payload(message: OutboundMessage) -> dict | None:
    """Build a WhatsApp location message payload from extra.location."""
    if not message.extra:
        return None
    loc = message.extra.get("location")
    if not loc:
        return None
    return {
        "messaging_product": "whatsapp",
        "to": message.to,
        "type": "location",
        "location": {
            "latitude": str(loc["latitude"]),
            "longitude": str(loc["longitude"]),
            "name": loc.get("name", ""),
            "address": loc.get("address", ""),
        },
    }


def build_contact_payload(message: OutboundMessage) -> dict | None:
    """Build a WhatsApp contacts message payload from extra.contact."""
    if not message.extra:
        return None
    contact = message.extra.get("contact")
    if not contact:
        return None

    name = contact.get("name", "")
    # Split name for WhatsApp's structured name format
    parts = name.split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""

    wa_contact: dict = {
        "name": {"formatted_name": name, "first_name": first, "last_name": last},
    }
    if phone := contact.get("phone"):
        wa_contact["phones"] = [{"phone": phone, "type": "CELL"}]
    if email := contact.get("email"):
        wa_contact["emails"] = [{"email": email, "type": "WORK"}]

    return {
        "messaging_product": "whatsapp",
        "to": message.to,
        "type": "contacts",
        "contacts": [wa_contact],
    }


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
    # Location message
    elif message.extra and message.extra.get("location"):
        payload = build_location_payload(message)
        if payload is None:
            payload = build_text_payload(message)
    # Contact message
    elif message.extra and message.extra.get("contact"):
        payload = build_contact_payload(message)
        if payload is None:
            payload = build_text_payload(message)
    # Default: text message
    else:
        payload = build_text_payload(message)

    return _apply_reply_context(payload, message.reply_to)


# ── Webhook / Inbound mappers ──

WHATSAPP_STATUS_MAP: dict[str, WebhookEventType] = {
    "sent": WebhookEventType.MESSAGE_DELIVERED,
    "delivered": WebhookEventType.MESSAGE_DELIVERED,
    "read": WebhookEventType.MESSAGE_DELIVERED,
    "failed": WebhookEventType.MESSAGE_FAILED,
}


def _detect_message_type(msg: dict) -> str:
    """Detect the WhatsApp message type."""
    return msg.get("type", "unknown")


def inbound_message_from_whatsapp(msg: dict, contacts: list[dict] | None = None) -> InboundMessage:
    """Parse a single WhatsApp webhook message into an InboundMessage DTO."""
    sender = msg.get("from", "")
    body = ""
    msg_type = msg.get("type", "text")

    if msg_type == "text":
        body = msg.get("text", {}).get("body", "")
    elif msg_type in ("image", "video", "audio", "document", "sticker"):
        body = msg.get(msg_type, {}).get("caption", "")

    timestamp = None
    if ts := msg.get("timestamp"):
        try:
            timestamp = datetime.fromtimestamp(int(ts), tz=UTC)
        except (ValueError, OSError):
            pass

    # Enrich sender name from contacts list
    sender_name = ""
    if contacts:
        for c in contacts:
            if c.get("wa_id") == sender:
                sender_name = c.get("profile", {}).get("name", "")
                break

    return InboundMessage(
        message_id=msg.get("id", ""),
        channel=MessageChannel.OTHER,
        sender=sender,
        body=body,
        received_at=timestamp,
        extra={
            "sender_name": sender_name,
            "message_type": msg_type,
            "context": msg.get("context", {}),
            "raw_message": msg,
        },
        provider_meta=ProviderMeta(
            provider="whatsapp",
            raw_id=msg.get("id", ""),
            raw_payload=msg,
            fetched_at=datetime.now(UTC),
        ),
    )


def webhook_event_from_whatsapp(data: dict) -> WebhookEvent:
    """Parse a Meta webhook payload into a normalized WebhookEvent.

    Meta wraps everything in: { object, entry: [{ changes: [{ value, field }] }] }
    """
    # Extract the first change value
    entries = data.get("entry", [])
    value = {}
    if entries:
        changes = entries[0].get("changes", [])
        if changes:
            value = changes[0].get("value", {})

    messages = value.get("messages", [])
    statuses = value.get("statuses", [])
    contacts = value.get("contacts", [])
    metadata = value.get("metadata", {})

    # Determine event type
    if messages:
        event_type = WebhookEventType.MESSAGE_RECEIVED
        provider_event_type = "messages"
    elif statuses:
        first_status = statuses[0].get("status", "") if statuses else ""
        event_type = WHATSAPP_STATUS_MAP.get(first_status, WebhookEventType.UNKNOWN)
        provider_event_type = "message_status"
    else:
        event_type = WebhookEventType.UNKNOWN
        provider_event_type = "unknown"

    # Build inbound messages for the payload
    inbound = [inbound_message_from_whatsapp(m, contacts) for m in messages]

    # Use first message/status ID as event ID
    event_id = ""
    if messages:
        event_id = messages[0].get("id", "")
    elif statuses:
        event_id = statuses[0].get("id", "")

    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider="whatsapp",
        provider_event_type=provider_event_type,
        payload=value,
        idempotency_key=event_id,
        received_at=datetime.now(UTC),
        extra={
            "metadata": metadata,
            "contacts": contacts,
            "inbound_messages": [m.model_dump() for m in inbound],
            "statuses": statuses,
        },
        provider_meta=ProviderMeta(
            provider="whatsapp",
            raw_id=event_id,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )
