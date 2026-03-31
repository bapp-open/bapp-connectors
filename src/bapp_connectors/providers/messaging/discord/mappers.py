"""
Discord <-> DTO mappers.

Converts between raw Discord API payloads and normalized framework DTOs.
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


def delivery_report_from_discord(response: dict, original_message_id: str = "") -> DeliveryReport:
    """Map a Discord message response to a DeliveryReport DTO."""
    message_id = response.get("id", "")
    return DeliveryReport(
        message_id=message_id or original_message_id,
        status=DeliveryStatus.SENT,
        extra={
            "message_id": message_id,
            "channel_id": response.get("channel_id", ""),
        },
    )


def build_payload(message: OutboundMessage) -> dict:
    """Build Discord message create payload from an OutboundMessage."""
    payload: dict = {}

    # Embed from extra
    if message.extra and message.extra.get("embeds"):
        payload["embeds"] = message.extra["embeds"]

    # Location — Discord has no native location; send as embed
    if message.extra and message.extra.get("location"):
        loc = message.extra["location"]
        name = loc.get("name", "Location")
        lat, lon = loc["latitude"], loc["longitude"]
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"
        payload["embeds"] = [{
            "title": name,
            "description": f"{lat}, {lon}",
            "url": maps_url,
            "color": 0x5865F2,
        }]
        return payload

    # Contact — send as embed
    if message.extra and message.extra.get("contact"):
        contact = message.extra["contact"]
        fields = []
        if phone := contact.get("phone"):
            fields.append({"name": "Phone", "value": phone, "inline": True})
        if email := contact.get("email"):
            fields.append({"name": "Email", "value": email, "inline": True})
        payload["embeds"] = [{
            "title": contact.get("name", "Contact"),
            "fields": fields,
            "color": 0x5865F2,
        }]
        return payload

    # Media — Discord uses URL embeds or file uploads; for URLs just include in content
    if message.extra and message.extra.get("media_type"):
        media_url = message.extra.get("media_url", "")
        caption = message.extra.get("caption", message.body)
        if media_url:
            payload["content"] = f"{caption}\n{media_url}" if caption else media_url
        else:
            payload["content"] = caption or ""
        return payload

    # Reply threading
    if message.reply_to:
        payload["message_reference"] = {"message_id": message.reply_to}

    # Default: text
    payload["content"] = message.body
    return payload


# ── Inbound ──


def inbound_message_from_discord(event: dict) -> InboundMessage | None:
    """Parse a Discord MESSAGE_CREATE event into an InboundMessage DTO.

    Returns None for non-message events or bot messages.
    """
    # Skip bot messages to avoid echo loops
    author = event.get("author", {})
    if author.get("bot"):
        return None

    content = event.get("content", "")
    channel_id = event.get("channel_id", "")
    sender = author.get("id", "")
    username = author.get("username", "")
    global_name = author.get("global_name", "")

    timestamp = None
    if ts := event.get("timestamp"):
        try:
            timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    # Build normalized attachments
    attachments = []
    for att in event.get("attachments", []):
        att_type = "document"
        ct = att.get("content_type", "")
        if ct.startswith("image/"):
            att_type = "image"
        elif ct.startswith("video/"):
            att_type = "video"
        elif ct.startswith("audio/"):
            att_type = "audio"
        attachments.append(MessageAttachment(
            type=att_type,
            url=att.get("url", ""),
            media_id=att.get("id", ""),
            mime_type=ct,
            filename=att.get("filename", ""),
            file_size=att.get("size"),
        ))

    return InboundMessage(
        message_id=event.get("id", ""),
        channel=MessageChannel.OTHER,
        sender=sender,
        sender_name=global_name or username,
        body=content,
        received_at=timestamp,
        attachments=attachments,
        extra={
            "channel_id": channel_id,
            "guild_id": event.get("guild_id", ""),
            "username": username,
            "global_name": global_name,
            "message_type": "text" if not attachments else attachments[0].type,
            "embeds": event.get("embeds", []),
            "message_reference": event.get("message_reference"),
            "raw_event": event,
        },
        provider_meta=ProviderMeta(
            provider="discord",
            raw_id=event.get("id", ""),
            raw_payload=event,
            fetched_at=datetime.now(UTC),
        ),
    )


def get_attachments_from_discord(message: InboundMessage) -> list[MessageAttachment]:
    """Extract attachments from a Discord inbound message."""
    raw_attachments = message.extra.get("attachments", [])
    result = []
    for att in raw_attachments:
        content_type = att.get("content_type", "")
        if content_type.startswith("image/"):
            att_type = "image"
        elif content_type.startswith("video/"):
            att_type = "video"
        elif content_type.startswith("audio/"):
            att_type = "audio"
        else:
            att_type = "document"

        result.append(MessageAttachment(
            type=att_type,
            media_id=att.get("id", ""),
            url=att.get("url", ""),
            mime_type=content_type,
            filename=att.get("filename", ""),
            file_size=att.get("size"),
            extra={"proxy_url": att.get("proxy_url", "")},
        ))
    return result


# ── Webhook ──


DISCORD_INTERACTION_TYPE_MAP: dict[int, str] = {
    1: "PING",
    2: "APPLICATION_COMMAND",
    3: "MESSAGE_COMPONENT",
    4: "APPLICATION_COMMAND_AUTOCOMPLETE",
    5: "MODAL_SUBMIT",
}


def webhook_event_from_discord(data: dict) -> WebhookEvent:
    """Parse a Discord interaction or gateway event into a WebhookEvent."""
    # Interaction webhook
    if "type" in data and isinstance(data.get("type"), int):
        interaction_type = data["type"]
        provider_event_type = DISCORD_INTERACTION_TYPE_MAP.get(interaction_type, "UNKNOWN")
        event_id = data.get("id", "")

        return WebhookEvent(
            event_id=event_id,
            event_type=WebhookEventType.UNKNOWN,
            provider="discord",
            provider_event_type=provider_event_type,
            payload=data,
            idempotency_key=event_id,
            received_at=datetime.now(UTC),
            extra={
                "interaction_type": interaction_type,
                "channel_id": data.get("channel_id", ""),
                "token": data.get("token", ""),
            },
            provider_meta=ProviderMeta(
                provider="discord",
                raw_id=event_id,
                raw_payload=data,
                fetched_at=datetime.now(UTC),
            ),
        )

    # Gateway MESSAGE_CREATE forwarded as webhook
    event_id = data.get("id", "")
    inbound = inbound_message_from_discord(data)

    return WebhookEvent(
        event_id=event_id,
        event_type=WebhookEventType.MESSAGE_RECEIVED,
        provider="discord",
        provider_event_type="MESSAGE_CREATE",
        payload=data,
        idempotency_key=event_id,
        received_at=datetime.now(UTC),
        extra={
            "inbound_messages": [inbound.model_dump()] if inbound else [],
            "channel_id": data.get("channel_id", ""),
        },
        provider_meta=ProviderMeta(
            provider="discord",
            raw_id=event_id,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )
