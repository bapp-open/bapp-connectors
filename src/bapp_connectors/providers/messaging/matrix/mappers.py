"""
Matrix <-> DTO mappers.

Converts between raw Matrix API payloads and normalized framework DTOs.
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


def delivery_report_from_matrix(response: dict, original_message_id: str = "") -> DeliveryReport:
    """Map a Matrix send response to a DeliveryReport DTO."""
    event_id = response.get("event_id", "")
    return DeliveryReport(
        message_id=event_id or original_message_id,
        status=DeliveryStatus.SENT,
        extra={"event_id": event_id},
    )


def build_payload(message: OutboundMessage) -> dict:
    """Build Matrix m.room.message content from an OutboundMessage."""
    # Location
    if message.extra and message.extra.get("location"):
        loc = message.extra["location"]
        geo_uri = f"geo:{loc['latitude']},{loc['longitude']}"
        return {
            "msgtype": "m.location",
            "body": loc.get("name") or geo_uri,
            "geo_uri": geo_uri,
        }

    # Contact — Matrix has no native contact type; send as formatted text
    if message.extra and message.extra.get("contact"):
        contact = message.extra["contact"]
        parts = [contact.get("name", "")]
        if phone := contact.get("phone"):
            parts.append(f"Phone: {phone}")
        if email := contact.get("email"):
            parts.append(f"Email: {email}")
        return {"msgtype": "m.text", "body": "\n".join(parts)}

    # Media
    if message.extra and message.extra.get("media_type"):
        media_type = message.extra["media_type"]
        mxc_url = message.extra.get("media_id") or message.extra.get("media_url", "")
        caption = message.extra.get("caption", message.body)
        msgtype_map = {
            "image": "m.image",
            "document": "m.file",
            "video": "m.video",
            "audio": "m.audio",
            "voice": "m.audio",
        }
        msgtype = msgtype_map.get(media_type, "m.file")
        content: dict = {
            "msgtype": msgtype,
            "body": caption or message.extra.get("filename", media_type),
            "url": mxc_url,
        }
        if filename := message.extra.get("filename"):
            content["filename"] = filename
        return content

    # Default: text
    content = {"msgtype": "m.text", "body": message.body}
    if message.html_body:
        content["format"] = "org.matrix.custom.html"
        content["formatted_body"] = message.html_body
    return content


# ── Inbound ──


def inbound_message_from_matrix(event: dict) -> InboundMessage | None:
    """Parse a Matrix room event into an InboundMessage DTO.

    Returns None for non-message events.
    """
    if event.get("type") != "m.room.message":
        return None

    content = event.get("content", {})
    sender = event.get("sender", "")
    room_id = event.get("room_id", "")
    msgtype = content.get("msgtype", "")

    body = content.get("body", "")

    timestamp = None
    if ts := event.get("origin_server_ts"):
        try:
            timestamp = datetime.fromtimestamp(ts / 1000, tz=UTC)
        except (ValueError, OSError):
            pass

    return InboundMessage(
        message_id=event.get("event_id", ""),
        channel=MessageChannel.OTHER,
        sender=sender,
        body=body,
        received_at=timestamp,
        extra={
            "room_id": room_id,
            "msgtype": msgtype,
            "content": content,
            "raw_event": event,
        },
        provider_meta=ProviderMeta(
            provider="matrix",
            raw_id=event.get("event_id", ""),
            raw_payload=event,
            fetched_at=datetime.now(UTC),
        ),
    )


def get_attachments_from_matrix(message: InboundMessage) -> list[MessageAttachment]:
    """Extract attachments from a Matrix inbound message."""
    content = message.extra.get("content", {})
    msgtype = content.get("msgtype", "")

    type_map = {
        "m.image": "image",
        "m.file": "document",
        "m.video": "video",
        "m.audio": "audio",
    }
    att_type = type_map.get(msgtype)
    if not att_type:
        return []

    info = content.get("info", {})
    return [MessageAttachment(
        type=att_type,
        media_id=content.get("url", ""),
        mime_type=info.get("mimetype", ""),
        filename=content.get("filename", content.get("body", "")),
        caption="",
        file_size=info.get("size"),
    )]


def get_location_from_matrix(message: InboundMessage) -> MessageLocation | None:
    """Extract location from a Matrix inbound message."""
    content = message.extra.get("content", {})
    if content.get("msgtype") != "m.location":
        return None

    geo_uri = content.get("geo_uri", "")
    if not geo_uri.startswith("geo:"):
        return None

    coords = geo_uri[4:].split(",")
    if len(coords) < 2:
        return None

    try:
        lat = float(coords[0])
        lon = float(coords[1].split(";")[0])  # strip optional params like ;u=35
    except ValueError:
        return None

    return MessageLocation(
        latitude=lat,
        longitude=lon,
        name=content.get("body", ""),
    )


# ── Webhook ──


MATRIX_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    "m.room.message": WebhookEventType.UNKNOWN,
    "m.room.member": WebhookEventType.UNKNOWN,
}


def webhook_event_from_matrix(data: dict) -> WebhookEvent:
    """Parse a Matrix appservice transaction or single event into a WebhookEvent.

    Appservice transactions: {"events": [...]}
    Single events (from sync or forwarded): the event dict itself
    """
    events = data.get("events", [data] if "type" in data else [])
    first = events[0] if events else {}

    event_type_str = first.get("type", "")
    event_type = MATRIX_WEBHOOK_EVENT_MAP.get(event_type_str, WebhookEventType.UNKNOWN)

    event_id = first.get("event_id", "")

    inbound = [inbound_message_from_matrix(e) for e in events]
    inbound = [m for m in inbound if m is not None]

    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider="matrix",
        provider_event_type=event_type_str,
        payload=data,
        idempotency_key=event_id,
        received_at=datetime.now(UTC),
        extra={
            "events_count": len(events),
            "inbound_messages": [m.model_dump() for m in inbound],
        },
        provider_meta=ProviderMeta(
            provider="matrix",
            raw_id=event_id,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )
