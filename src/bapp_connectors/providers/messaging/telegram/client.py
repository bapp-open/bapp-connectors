"""
Telegram Bot API client — raw HTTP calls only, no business logic.

Auth is via bot token embedded in the URL path:
    https://api.telegram.org/bot{token}/{method}
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class TelegramApiClient:
    """
    Low-level Telegram Bot API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.

    All Telegram API methods are POST requests to:
        https://api.telegram.org/bot{token}/{method_name}
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def _call(self, method: str, **params) -> dict:
        """Call a Telegram Bot API method. Returns the 'result' field."""
        # Filter out None values
        payload = {k: v for k, v in params.items() if v is not None}
        response = self.http.call("POST", method, json=payload)
        if isinstance(response, dict) and "result" in response:
            return response["result"]
        return response

    # ── Auth / Connection Test ──

    def get_me(self) -> dict:
        """getMe — verify bot token and get bot info."""
        return self._call("getMe")

    def test_auth(self) -> bool:
        """Verify credentials by calling getMe."""
        try:
            result = self.get_me()
            return isinstance(result, dict) and result.get("is_bot", False)
        except Exception:
            return False

    # ── Text Messages ──

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        reply_parameters: dict | None = None,
        reply_markup: dict | None = None,
        link_preview_options: dict | None = None,
    ) -> dict:
        """sendMessage — send a text message."""
        return self._call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            link_preview_options=link_preview_options,
        )

    # ── Media Messages ──

    def send_photo(
        self,
        chat_id: int | str,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendPhoto — send a photo via URL or file_id."""
        return self._call(
            "sendPhoto",
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            reply_parameters=reply_parameters,
        )

    def send_document(
        self,
        chat_id: int | str,
        document: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendDocument — send a document via URL or file_id."""
        return self._call(
            "sendDocument",
            chat_id=chat_id,
            document=document,
            caption=caption,
            parse_mode=parse_mode,
            reply_parameters=reply_parameters,
        )

    def send_video(
        self,
        chat_id: int | str,
        video: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendVideo — send a video via URL or file_id."""
        return self._call(
            "sendVideo",
            chat_id=chat_id,
            video=video,
            caption=caption,
            parse_mode=parse_mode,
            reply_parameters=reply_parameters,
        )

    def send_audio(
        self,
        chat_id: int | str,
        audio: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendAudio — send an audio file via URL or file_id."""
        return self._call(
            "sendAudio",
            chat_id=chat_id,
            audio=audio,
            caption=caption,
            parse_mode=parse_mode,
            reply_parameters=reply_parameters,
        )

    def send_voice(
        self,
        chat_id: int | str,
        voice: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendVoice — send a voice message via URL or file_id."""
        return self._call(
            "sendVoice",
            chat_id=chat_id,
            voice=voice,
            caption=caption,
            parse_mode=parse_mode,
            reply_parameters=reply_parameters,
        )

    def send_sticker(
        self,
        chat_id: int | str,
        sticker: str,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendSticker — send a sticker via URL or file_id."""
        return self._call(
            "sendSticker",
            chat_id=chat_id,
            sticker=sticker,
            reply_parameters=reply_parameters,
        )

    def send_animation(
        self,
        chat_id: int | str,
        animation: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendAnimation — send a GIF/animation via URL or file_id."""
        return self._call(
            "sendAnimation",
            chat_id=chat_id,
            animation=animation,
            caption=caption,
            parse_mode=parse_mode,
            reply_parameters=reply_parameters,
        )

    # ── Location & Contact ──

    def send_location(
        self,
        chat_id: int | str,
        latitude: float,
        longitude: float,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendLocation — send a location point."""
        return self._call(
            "sendLocation",
            chat_id=chat_id,
            latitude=latitude,
            longitude=longitude,
            reply_parameters=reply_parameters,
        )

    def send_contact(
        self,
        chat_id: int | str,
        phone_number: str,
        first_name: str,
        last_name: str | None = None,
        reply_parameters: dict | None = None,
    ) -> dict:
        """sendContact — send a phone contact."""
        return self._call(
            "sendContact",
            chat_id=chat_id,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            reply_parameters=reply_parameters,
        )

    # ── Message Management ──

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        """editMessageText — edit an existing text message."""
        return self._call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    def delete_message(self, chat_id: int | str, message_id: int) -> bool:
        """deleteMessage — delete a message (must be < 48h old)."""
        result = self._call("deleteMessage", chat_id=chat_id, message_id=message_id)
        return result is True or (isinstance(result, dict) and result.get("ok", False))

    def forward_message(self, chat_id: int | str, from_chat_id: int | str, message_id: int) -> dict:
        """forwardMessage — forward a message from another chat."""
        return self._call(
            "forwardMessage",
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
        )

    # ── Webhook Management ──

    def set_webhook(self, url: str, secret_token: str | None = None, allowed_updates: list[str] | None = None) -> bool:
        """setWebhook — register a webhook URL."""
        result = self._call(
            "setWebhook",
            url=url,
            secret_token=secret_token,
            allowed_updates=allowed_updates,
        )
        return result is True

    def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        """deleteWebhook — remove the webhook."""
        result = self._call("deleteWebhook", drop_pending_updates=drop_pending_updates)
        return result is True

    def get_webhook_info(self) -> dict:
        """getWebhookInfo — get current webhook status."""
        return self._call("getWebhookInfo")
