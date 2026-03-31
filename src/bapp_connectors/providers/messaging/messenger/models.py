"""
Pydantic models for Facebook Messenger Send API request/response payloads.

These model the raw Messenger API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel

# ── Response models ──


class MessengerSendResponse(BaseModel):
    """Response from the Send API."""

    recipient_id: str = ""
    message_id: str = ""


# ── Webhook models ──


class MessengerWebhookSender(BaseModel):
    """Sender from a webhook message."""

    id: str = ""


class MessengerWebhookRecipient(BaseModel):
    """Recipient from a webhook message."""

    id: str = ""


class MessengerWebhookMessage(BaseModel):
    """A single message from a webhook event."""

    mid: str = ""
    text: str = ""
    attachments: list[dict] = []
    reply_to: dict = {}
    quick_reply: dict = {}


class MessengerWebhookPostback(BaseModel):
    """A postback event from a webhook."""

    mid: str = ""
    title: str = ""
    payload: str = ""


class MessengerWebhookMessaging(BaseModel):
    """A single messaging entry from a webhook event."""

    sender: MessengerWebhookSender = MessengerWebhookSender()
    recipient: MessengerWebhookRecipient = MessengerWebhookRecipient()
    timestamp: int = 0
    message: MessengerWebhookMessage | None = None
    postback: MessengerWebhookPostback | None = None
    delivery: dict | None = None
    read: dict | None = None
