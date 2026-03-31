"""
Facebook Messenger <-> DTO mappers.

Converts between raw Messenger API payloads and normalized framework DTOs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    InboundMessage,
    MessageAttachment,
    MessageChannel,
    MessageLocation,
    OutboundMessage,
    ProviderMeta,
    WebhookEvent,
    WebhookEventType,
)

# ── Outbound ──


def delivery_report_from_messenger(response: dict, original_message_id: str = "") -> DeliveryReport:
    """Map a Messenger Send API response to a DeliveryReport DTO."""
    message_id = response.get("message_id", "")
    return DeliveryReport(
        message_id=message_id or original_message_id,
        status=DeliveryStatus.SENT,
        extra={
            "message_id": message_id,
            "recipient_id": response.get("recipient_id", ""),
        },
    )


def build_text_payload(message: OutboundMessage) -> dict:
    """Build a Messenger text message payload."""
    return {
        "recipient": {"id": message.to},
        "messaging_type": "RESPONSE",
        "message": {"text": message.body},
    }


def build_attachment_payload(message: OutboundMessage) -> dict | None:
    """Build a Messenger attachment payload from extra fields."""
    if not message.extra:
        return None

    media_type = message.extra.get("media_type")
    type_map = {
        "image": "image",
        "document": "file",
        "video": "video",
        "audio": "audio",
        "voice": "audio",
    }
    att_type = type_map.get(media_type)
    if not att_type:
        return None

    # By media_id (reusable attachment)
    if media_id := message.extra.get("media_id"):
        return {
            "recipient": {"id": message.to},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": att_type,
                    "payload": {"attachment_id": media_id},
                },
            },
        }

    # By URL
    if media_url := message.extra.get("media_url"):
        return {
            "recipient": {"id": message.to},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": att_type,
                    "payload": {"url": media_url, "is_reusable": True},
                },
            },
        }

    return None


def build_payload(message: OutboundMessage) -> dict:
    """Build the appropriate Messenger payload based on the message content."""
    # Media
    if message.extra and message.extra.get("media_type"):
        payload = build_attachment_payload(message)
        if payload:
            return payload

    # Location — Messenger doesn't support outbound location; send as text
    if message.extra and message.extra.get("location"):
        loc = message.extra["location"]
        text = f"{loc.get('name', 'Location')}: {loc['latitude']}, {loc['longitude']}"
        if addr := loc.get("address"):
            text += f"\n{addr}"
        return {
            "recipient": {"id": message.to},
            "messaging_type": "RESPONSE",
            "message": {"text": text},
        }

    # Contact — send as text
    if message.extra and message.extra.get("contact"):
        contact = message.extra["contact"]
        parts = [contact.get("name", "")]
        if phone := contact.get("phone"):
            parts.append(f"Phone: {phone}")
        if email := contact.get("email"):
            parts.append(f"Email: {email}")
        return {
            "recipient": {"id": message.to},
            "messaging_type": "RESPONSE",
            "message": {"text": "\n".join(parts)},
        }

    # Raw payload passthrough
    if message.extra and "raw_payload" in message.extra:
        return message.extra["raw_payload"]

    # Default: text
    return build_text_payload(message)


# ── Inbound ──


def inbound_message_from_messenger(messaging: dict) -> InboundMessage | None:
    """Parse a single Messenger webhook messaging entry into an InboundMessage DTO.

    Returns None for non-message entries (delivery, read, etc.).
    """
    msg = messaging.get("message")
    if not msg:
        return None

    sender = messaging.get("sender", {}).get("id", "")
    body = msg.get("text", "")

    timestamp = None
    if ts := messaging.get("timestamp"):
        try:
            timestamp = datetime.fromtimestamp(ts / 1000, tz=UTC)
        except (ValueError, OSError):
            pass

    # Build normalized attachments and location
    type_map = {"image": "image", "video": "video", "audio": "audio", "file": "document"}
    attachments = []
    location = None
    for att in msg.get("attachments", []):
        raw_type = att.get("type", "")
        payload = att.get("payload", {})

        if raw_type == "location":
            coords = payload.get("coordinates", {})
            location = MessageLocation(
                latitude=coords.get("lat", 0.0),
                longitude=coords.get("long", 0.0),
            )
            continue

        att_type = type_map.get(raw_type)
        if not att_type:
            continue
        attachments.append(MessageAttachment(
            type=att_type,
            url=payload.get("url", ""),
            media_id=payload.get("sticker_id", ""),
            file_size=payload.get("size"),
        ))

    msg_type = "text"
    if attachments:
        msg_type = attachments[0].type
    elif location:
        msg_type = "location"

    return InboundMessage(
        message_id=msg.get("mid", ""),
        channel=MessageChannel.OTHER,
        sender=sender,
        body=body,
        received_at=timestamp,
        attachments=attachments,
        location=location,
        extra={
            "message_type": msg_type,
            "sender_id": sender,
            "recipient_id": messaging.get("recipient", {}).get("id", ""),
            "quick_reply": msg.get("quick_reply", {}),
            "reply_to": msg.get("reply_to", {}),
            "raw_messaging": messaging,
        },
        provider_meta=ProviderMeta(
            provider="messenger",
            raw_id=msg.get("mid", ""),
            raw_payload=messaging,
            fetched_at=datetime.now(UTC),
        ),
    )


def get_attachments_from_messenger(message: InboundMessage) -> list[MessageAttachment]:
    """Extract attachments from a Messenger inbound message."""
    raw_attachments = message.extra.get("attachments", [])
    result = []
    for att in raw_attachments:
        att_type = att.get("type", "")
        payload = att.get("payload", {})

        type_map = {
            "image": "image",
            "video": "video",
            "audio": "audio",
            "file": "document",
        }
        normalized_type = type_map.get(att_type)
        if not normalized_type:
            continue

        result.append(MessageAttachment(
            type=normalized_type,
            url=payload.get("url", ""),
            media_id=payload.get("sticker_id", ""),
            file_size=payload.get("size"),
        ))
    return result


def get_location_from_messenger(message: InboundMessage) -> MessageLocation | None:
    """Extract location from a Messenger inbound message.

    Messenger sends location as an attachment with type "location".
    """
    raw_attachments = message.extra.get("attachments", [])
    for att in raw_attachments:
        if att.get("type") != "location":
            continue
        payload = att.get("payload", {})
        coords = payload.get("coordinates", {})
        lat = coords.get("lat")
        lon = coords.get("long")
        if lat is not None and lon is not None:
            return MessageLocation(
                latitude=float(lat),
                longitude=float(lon),
                name=att.get("title", ""),
                address=payload.get("url", ""),
            )
    return None


# ── Webhook ──


MESSENGER_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    "messages": WebhookEventType.MESSAGE_RECEIVED,
    "messaging_postbacks": WebhookEventType.MESSAGE_RECEIVED,
    "message_deliveries": WebhookEventType.MESSAGE_DELIVERED,
    "message_reads": WebhookEventType.MESSAGE_DELIVERED,
}


def webhook_event_from_messenger(data: dict) -> WebhookEvent:
    """Parse a Meta webhook payload into a normalized WebhookEvent.

    Meta sends: { object: "page", entry: [{ messaging: [...] }] }
    """
    entries = data.get("entry", [])
    all_messaging = []
    for entry in entries:
        all_messaging.extend(entry.get("messaging", []))

    # Determine event type from first messaging entry
    provider_event_type = "unknown"
    if all_messaging:
        first = all_messaging[0]
        if first.get("message"):
            provider_event_type = "messages"
        elif first.get("postback"):
            provider_event_type = "messaging_postbacks"
        elif first.get("delivery"):
            provider_event_type = "message_deliveries"
        elif first.get("read"):
            provider_event_type = "message_reads"

    event_type = MESSENGER_WEBHOOK_EVENT_MAP.get(provider_event_type, WebhookEventType.UNKNOWN)

    inbound = [inbound_message_from_messenger(m) for m in all_messaging]
    inbound = [m for m in inbound if m is not None]

    event_id = ""
    if inbound:
        event_id = inbound[0].message_id

    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider="messenger",
        provider_event_type=provider_event_type,
        payload=data,
        idempotency_key=event_id,
        received_at=datetime.now(UTC),
        extra={
            "messaging_count": len(all_messaging),
            "inbound_messages": [m.model_dump() for m in inbound],
        },
        provider_meta=ProviderMeta(
            provider="messenger",
            raw_id=event_id,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )
