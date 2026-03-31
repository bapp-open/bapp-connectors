"""
Pydantic models for Instagram Messaging API request/response payloads.

These model the raw Instagram DM API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel

# ── Response models ──


class InstagramSendResponse(BaseModel):
    """Response from the Send API."""

    recipient_id: str = ""
    message_id: str = ""


# ── Webhook models ──


class InstagramWebhookMessage(BaseModel):
    """A single message from an Instagram webhook event."""

    mid: str = ""
    text: str = ""
    attachments: list[dict] = []
    reply_to: dict = {}
    is_echo: bool = False
    is_deleted: bool = False


class InstagramWebhookReaction(BaseModel):
    """A reaction event from an Instagram webhook."""

    mid: str = ""
    action: str = ""  # "react" or "unreact"
    reaction: str = ""  # emoji
    emoji: str = ""


class InstagramWebhookMessaging(BaseModel):
    """A single messaging entry from an Instagram webhook."""

    sender: dict = {}
    recipient: dict = {}
    timestamp: int = 0
    message: InstagramWebhookMessage | None = None
    postback: dict | None = None
    reaction: InstagramWebhookReaction | None = None
    read: dict | None = None
