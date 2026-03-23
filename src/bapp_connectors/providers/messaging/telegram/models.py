"""
Pydantic models for Telegram Bot API request/response payloads.

These model the raw Telegram API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Response models ──


class TelegramUser(BaseModel):
    """Telegram User object."""

    id: int = 0
    is_bot: bool = False
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""


class TelegramChat(BaseModel):
    """Telegram Chat object."""

    id: int = 0
    type: str = ""  # private, group, supergroup, channel
    title: str = ""
    username: str = ""
    first_name: str = ""
    last_name: str = ""


class TelegramMessage(BaseModel):
    """Telegram Message object (simplified)."""

    message_id: int = 0
    from_: TelegramUser | None = Field(None, alias="from")
    chat: TelegramChat = TelegramChat()
    date: int = 0
    text: str = ""
    caption: str = ""

    model_config = {"populate_by_name": True}


class TelegramApiResponse(BaseModel):
    """Standard Telegram API response wrapper."""

    ok: bool = False
    result: dict | list | bool | None = None
    description: str = ""
    error_code: int | None = None


# ── Webhook models ──


class TelegramUpdate(BaseModel):
    """Telegram Update object from webhook."""

    update_id: int = 0
    message: dict | None = None
    edited_message: dict | None = None
    channel_post: dict | None = None
    callback_query: dict | None = None


class TelegramWebhookInfo(BaseModel):
    """Response from getWebhookInfo."""

    url: str = ""
    has_custom_certificate: bool = False
    pending_update_count: int = 0
    last_error_date: int | None = None
    last_error_message: str = ""
    max_connections: int | None = None
    allowed_updates: list[str] = []
