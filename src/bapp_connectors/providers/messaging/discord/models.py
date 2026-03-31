"""
Pydantic models for Discord API request/response payloads.

These model the raw Discord API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel

# ── Response models ──


class DiscordUser(BaseModel):
    """Discord user object."""

    id: str = ""
    username: str = ""
    discriminator: str = ""
    global_name: str | None = None
    avatar: str | None = None
    bot: bool = False


class DiscordMessage(BaseModel):
    """Discord message object (simplified)."""

    id: str = ""
    channel_id: str = ""
    author: DiscordUser = DiscordUser()
    content: str = ""
    timestamp: str = ""
    attachments: list[dict] = []
    embeds: list[dict] = []
    message_reference: dict | None = None


# ── Webhook / Gateway event models ──


class DiscordInteraction(BaseModel):
    """Discord interaction from webhook."""

    id: str = ""
    application_id: str = ""
    type: int = 0  # 1=PING, 2=APPLICATION_COMMAND, 3=MESSAGE_COMPONENT
    data: dict | None = None
    channel_id: str = ""
    token: str = ""
    member: dict | None = None
    user: dict | None = None
    message: dict | None = None
