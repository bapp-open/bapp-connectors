"""
Discord Bot API client — raw HTTP calls only, no business logic.

Uses Discord REST API v10. Bot token is passed via "Bot {token}" Authorization header.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

# Discord ids are snowflakes: unsigned 64-bit integers written in decimal.
_SNOWFLAKE = re.compile(r"[0-9]{1,20}")


def _ai_snowflake(value: Any, what: str) -> str:
    """A Discord id from an agent: ASCII digits only, so it stays one path segment."""
    if not isinstance(value, str) or not _SNOWFLAKE.fullmatch(value):
        raise ValidationError(f"{what} must be a numeric Discord id (snowflake).")
    return value


class DiscordApiClient:
    """Low-level Discord REST API client."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    # ── Auth / Connection Test ──

    @ai_method("read", "The bot's own Discord user: id, username, avatar, flags.")
    def get_current_user(self) -> dict:
        """GET /users/@me — get the bot's own user info."""
        return self.http.call("GET", "users/@me")

    def test_auth(self) -> bool:
        try:
            self.get_current_user()
            return True
        except Exception:
            return False

    # ── Messages ──

    def send_message(
        self,
        channel_id: str,
        content: str = "",
        embeds: list[dict] | None = None,
        message_reference: dict | None = None,
    ) -> dict:
        """POST /channels/{channel_id}/messages"""
        payload: dict[str, Any] = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds
        if message_reference:
            payload["message_reference"] = message_reference
        return self.http.call("POST", f"channels/{channel_id}/messages", json=payload)

    def send_file(
        self,
        channel_id: str,
        file_data: bytes,
        filename: str,
        content: str = "",
        content_type: str = "application/octet-stream",
    ) -> dict:
        """POST /channels/{channel_id}/messages with multipart file upload."""
        import io

        files = {"file": (filename, io.BytesIO(file_data), content_type)}
        data: dict[str, Any] = {}
        if content:
            data["content"] = content
        return self.http.call(
            "POST", f"channels/{channel_id}/messages",
            data=data, files=files,
        )

    def edit_message(self, channel_id: str, message_id: str, content: str = "", embeds: list[dict] | None = None) -> dict:
        """PATCH /channels/{channel_id}/messages/{message_id}"""
        payload: dict[str, Any] = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds
        return self.http.call("PATCH", f"channels/{channel_id}/messages/{message_id}", json=payload)

    def delete_message(self, channel_id: str, message_id: str) -> None:
        """DELETE /channels/{channel_id}/messages/{message_id}"""
        self.http.call("DELETE", f"channels/{channel_id}/messages/{message_id}")

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> None:
        """PUT /channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me"""
        self.http.call("PUT", f"channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me")

    # ── Channels ──

    @ai_method("read", "One Discord channel the bot can see: name, type, topic, guild.")
    def get_channel(self, channel_id: str) -> dict:
        """GET /channels/{channel_id}"""
        return self.http.call("GET", f"channels/{_ai_snowflake(channel_id, 'channel_id')}")

    @ai_method(
        "read",
        "Message history of a Discord channel the bot can read, newest first (max 100). "
        "Page with 'before' (older than that message id) or 'after'. Reading does not acknowledge anything.",
    )
    def get_channel_messages(
        self,
        channel_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
    ) -> list:
        """GET /channels/{channel_id}/messages"""
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 100))}
        if before:
            params["before"] = _ai_snowflake(before, "before")
        if after:
            params["after"] = _ai_snowflake(after, "after")
        return self.http.call("GET", f"channels/{_ai_snowflake(channel_id, 'channel_id')}/messages", params=params)

    # ── Guilds ──

    @ai_method("read", "The Discord servers (guilds) the bot is a member of: id, name, icon, permissions.")
    def list_guilds(self) -> list:
        """GET /users/@me/guilds"""
        return self.http.call("GET", "users/@me/guilds")

    @ai_method("read", "One Discord server (guild) the bot is in: name, owner, roles, features.")
    def get_guild(self, guild_id: str) -> dict:
        """GET /guilds/{guild_id}"""
        return self.http.call("GET", f"guilds/{_ai_snowflake(guild_id, 'guild_id')}")

    @ai_method("read", "The channels of a Discord server (guild) the bot is in.")
    def get_guild_channels(self, guild_id: str) -> list:
        """GET /guilds/{guild_id}/channels"""
        return self.http.call("GET", f"guilds/{_ai_snowflake(guild_id, 'guild_id')}/channels")

    # ── Interactions (webhook responses) ──

    def respond_to_interaction(self, interaction_id: str, interaction_token: str, content: str = "", embeds: list[dict] | None = None) -> dict:
        """POST /interactions/{id}/{token}/callback"""
        data: dict[str, Any] = {"type": 4, "data": {}}
        if content:
            data["data"]["content"] = content
        if embeds:
            data["data"]["embeds"] = embeds
        return self.http.call("POST", f"interactions/{interaction_id}/{interaction_token}/callback", json=data)
