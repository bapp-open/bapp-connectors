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


class OutboundMessage(BaseDTO):
    """Normalized outbound message.

    message_id is a caller-supplied correlation identifier, not necessarily an
    RFC email Message-ID. Provider-specific wire identifiers belong in extra.
    For SMTP, extra.rfc_message_id optionally supplies the RFC Message-ID;
    reply_to is the parent's RFC Message-ID and extra.references carries its
    References chain. extra.reply_to is a separate Reply-To email address.
    """

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


class InboundMessage(BaseDTO):
    """Normalized inbound message (webhook-received)."""

    message_id: str
    channel: MessageChannel
    sender: str = ""
    sender_name: str = ""
    body: str = ""
    received_at: datetime | None = None
    attachments: list[MessageAttachment] = []
    location: MessageLocation | None = None
    contacts: list[MessageContact] = []
    extra: dict = {}


class DeliveryReport(BaseDTO):
    """Delivery status report for a sent message.

    SMTP preserves a supplied correlation message_id, otherwise returns the
    generated RFC ID. extra.rfc_message_id contains the assigned wire ID, also
    on submission failure. SENT denotes SMTP acceptance, not confirmed delivery.
    """

    message_id: str
    status: DeliveryStatus
    error: str = ""
    delivered_at: datetime | None = None
    extra: dict = {}
