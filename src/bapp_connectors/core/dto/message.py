"""
Normalized DTOs for messaging (SMS, email, WhatsApp, etc.).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from .base import BaseDTO


class MessageChannel(StrEnum):
    SMS = "sms"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    OTHER = "other"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    REJECTED = "rejected"


class OutboundMessage(BaseDTO):
    """Normalized outbound message."""

    message_id: str = ""
    channel: MessageChannel
    to: str
    reply_to: str = ""  # ID of the message being replied to (for conversational context)
    subject: str = ""
    body: str = ""
    html_body: str = ""
    template_id: str = ""
    template_vars: dict = {}
    attachments: list[dict] = []
    extra: dict = {}


class InboundMessage(BaseDTO):
    """Normalized inbound message (webhook-received)."""

    message_id: str
    channel: MessageChannel
    sender: str = ""
    body: str = ""
    received_at: datetime | None = None
    extra: dict = {}


class MessageAttachment(BaseDTO):
    """Normalized attachment from an inbound message."""

    type: str  # "image", "document", "video", "audio", "voice", "sticker", "animation"
    media_id: str = ""
    url: str = ""
    mime_type: str = ""
    filename: str = ""
    caption: str = ""
    file_size: int | None = None
    extra: dict = {}


class MessageLocation(BaseDTO):
    """Normalized location from an inbound message."""

    latitude: float
    longitude: float
    name: str = ""
    address: str = ""
    extra: dict = {}


class MessageContact(BaseDTO):
    """Normalized contact shared via a message."""

    name: str = ""
    phone: str = ""
    email: str = ""
    extra: dict = {}


class DeliveryReport(BaseDTO):
    """Delivery status report for a sent message."""

    message_id: str
    status: DeliveryStatus
    error: str = ""
    delivered_at: datetime | None = None
    extra: dict = {}
