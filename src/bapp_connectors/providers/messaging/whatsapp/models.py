"""
Pydantic models for WhatsApp Cloud API request/response payloads.

These model the raw WhatsApp API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Response models ──


class WhatsAppMessageContact(BaseModel):
    """Contact info returned after sending a message."""

    input: str = ""
    wa_id: str = ""


class WhatsAppMessageInfo(BaseModel):
    """Message info returned after sending."""

    id: str = ""


class WhatsAppSendResponse(BaseModel):
    """Response from WhatsApp messages endpoint."""

    messaging_product: str = "whatsapp"
    contacts: list[WhatsAppMessageContact] = []
    messages: list[WhatsAppMessageInfo] = []


# ── Webhook models ──


class WhatsAppWebhookMetadata(BaseModel):
    """Metadata from a webhook event."""

    display_phone_number: str = ""
    phone_number_id: str = ""


class WhatsAppWebhookContact(BaseModel):
    """Contact from a webhook message."""

    wa_id: str = ""
    profile: dict = {}


class WhatsAppWebhookMessage(BaseModel):
    """A single message from a webhook event."""

    from_: str = Field("", alias="from")
    id: str = ""
    timestamp: str = ""
    type: str = ""
    text: dict = {}
    image: dict = {}
    video: dict = {}
    audio: dict = {}
    document: dict = {}
    location: dict = {}
    contacts: list[dict] = []
    interactive: dict = {}
    button: dict = {}
    reaction: dict = {}
    context: dict = {}

    model_config = {"populate_by_name": True}


class WhatsAppWebhookStatus(BaseModel):
    """A status update from a webhook event."""

    id: str = ""
    status: str = ""
    timestamp: str = ""
    recipient_id: str = ""


class WhatsAppWebhookValue(BaseModel):
    """The 'value' of a webhook change."""

    messaging_product: str = ""
    metadata: WhatsAppWebhookMetadata = WhatsAppWebhookMetadata()
    contacts: list[WhatsAppWebhookContact] = []
    messages: list[WhatsAppWebhookMessage] = []
    statuses: list[WhatsAppWebhookStatus] = []
