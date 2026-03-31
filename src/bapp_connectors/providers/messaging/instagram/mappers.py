"""
Instagram DM <-> DTO mappers.

Converts between raw Instagram Messaging API payloads and normalized framework DTOs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    InboundMessage,
    MessageAttachment,
    MessageChannel,
    OutboundMessage,
    ProviderMeta,
    WebhookEvent,
    WebhookEventType,
)

# ── Outbound ──


def delivery_report_from_instagram(response: dict, original_message_id: str = "") -> DeliveryReport:
    """Map an Instagram Send API response to a DeliveryReport DTO."""
    message_id = response.get("message_id", "")
    return DeliveryReport(
        message_id=message_id or original_message_id,
        status=DeliveryStatus.SENT,
        extra={
            "message_id": message_id,
            "recipient_id": response.get("recipient_id", ""),
        },
    )


def build_payload(message: OutboundMessage) -> dict:
    """Build the appropriate Instagram DM payload based on the message content."""
    # Media attachment
    if message.extra and message.extra.get("media_type"):
        media_type = message.extra["media_type"]
        type_map = {"image": "image", "video": "video", "audio": "audio", "document": "file"}
        att_type = type_map.get(media_type, "file")

        if media_url := message.extra.get("media_url"):
            return {
                "recipient": {"id": message.to},
                "message": {
                    "attachment": {
                        "type": att_type,
                        "payload": {"url": media_url},
                    },
                },
            }

    # Story reply
    if message.extra and message.extra.get("story_id"):
        return {
            "recipient": {"id": message.to},
            "message": {
                "text": message.body,
                "reply_to": {"story_id": message.extra["story_id"]},
            },
        }

    # Location — Instagram DM doesn't support outbound location; send as text
    if message.extra and message.extra.get("location"):
        loc = message.extra["location"]
        text = f"{loc.get('name', 'Location')}: {loc['latitude']}, {loc['longitude']}"
        return {"recipient": {"id": message.to}, "message": {"text": text}}

    # Contact — send as text
    if message.extra and message.extra.get("contact"):
        contact = message.extra["contact"]
        parts = [contact.get("name", "")]
        if phone := contact.get("phone"):
            parts.append(f"Phone: {phone}")
        return {"recipient": {"id": message.to}, "message": {"text": "\n".join(parts)}}

    # Raw payload passthrough
    if message.extra and "raw_payload" in message.extra:
        return message.extra["raw_payload"]

    # Default: text
    return {"recipient": {"id": message.to}, "message": {"text": message.body}}


# ── Inbound ──


def inbound_message_from_instagram(messaging: dict) -> InboundMessage | None:
    """Parse a single Instagram webhook messaging entry into an InboundMessage DTO.

    Returns None for echo messages, deleted messages, or non-message entries.
    """
    msg = messaging.get("message")
    if not msg:
        return None

    # Skip echo messages (sent by our own page)
    if msg.get("is_echo"):
        return None

    if msg.get("is_deleted"):
        return None

    sender = messaging.get("sender", {}).get("id", "")
    body = msg.get("text", "")

    timestamp = None
    if ts := messaging.get("timestamp"):
        try:
            timestamp = datetime.fromtimestamp(ts / 1000, tz=UTC)
        except (ValueError, OSError):
            pass

    # Build normalized attachments
    type_map = {"image": "image", "video": "video", "audio": "audio", "file": "document"}
    attachments = []
    for att in msg.get("attachments", []):
        raw_type = att.get("type", "")
        payload = att.get("payload", {})

        att_type = type_map.get(raw_type)
        if not att_type:
            # Instagram also sends "story_mention", "reel", "ig_reel" as attachment types
            att_type = raw_type or "unknown"

        attachments.append(MessageAttachment(
            type=att_type,
            url=payload.get("url", ""),
        ))

    msg_type = "text"
    if attachments:
        msg_type = attachments[0].type

    return InboundMessage(
        message_id=msg.get("mid", ""),
        channel=MessageChannel.OTHER,
        sender=sender,
        body=body,
        received_at=timestamp,
        attachments=attachments,
        extra={
            "message_type": msg_type,
            "sender_id": sender,
            "recipient_id": messaging.get("recipient", {}).get("id", ""),
            "reply_to": msg.get("reply_to", {}),
            "raw_messaging": messaging,
        },
        provider_meta=ProviderMeta(
            provider="instagram",
            raw_id=msg.get("mid", ""),
            raw_payload=messaging,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Webhook ──


INSTAGRAM_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    "messages": WebhookEventType.MESSAGE_RECEIVED,
    "messaging_postbacks": WebhookEventType.MESSAGE_RECEIVED,
    "message_reactions": WebhookEventType.UNKNOWN,
    "message_reads": WebhookEventType.MESSAGE_DELIVERED,
}


def webhook_event_from_instagram(data: dict) -> WebhookEvent:
    """Parse a Meta webhook payload into a normalized WebhookEvent.

    Instagram webhooks: { object: "instagram", entry: [{ messaging: [...] }] }
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
        elif first.get("reaction"):
            provider_event_type = "message_reactions"
        elif first.get("read"):
            provider_event_type = "message_reads"

    event_type = INSTAGRAM_WEBHOOK_EVENT_MAP.get(provider_event_type, WebhookEventType.UNKNOWN)

    inbound = [inbound_message_from_instagram(m) for m in all_messaging]
    inbound = [m for m in inbound if m is not None]

    event_id = ""
    if inbound:
        event_id = inbound[0].message_id

    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider="instagram",
        provider_event_type=provider_event_type,
        payload=data,
        idempotency_key=event_id,
        received_at=datetime.now(UTC),
        extra={
            "messaging_count": len(all_messaging),
            "inbound_messages": [m.model_dump() for m in inbound],
        },
        provider_meta=ProviderMeta(
            provider="instagram",
            raw_id=event_id,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )
