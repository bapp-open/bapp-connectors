"""
Telegram Bot API messaging adapter — implements MessagingPort.

Uses the Telegram Bot API for sending text, media, stickers, locations,
contacts, and interactive content (inline keyboards).

Auth: bot token embedded in the base URL path.
"""

from __future__ import annotations

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
)
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.telegram.client import TelegramApiClient
from bapp_connectors.providers.messaging.telegram.manifest import manifest
from bapp_connectors.providers.messaging.telegram.mappers import (
    build_payload,
    delivery_report_from_telegram,
)


class TelegramMessagingAdapter(MessagingPort):
    """
    Telegram Bot API adapter.

    Implements:
    - MessagingPort: send, send_bulk (reply inherited from MessagingPort)

    Supports via OutboundMessage:
    - Text messages (default) with HTML/Markdown parsing
    - Media messages (set extra.media_type + extra.media_url or extra.media_id)
    - Reply threading (set reply_to to a message_id)
    - Inline keyboards (set extra.reply_markup)
    - Raw API calls (set extra.raw_method + extra.raw_payload)
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._parse_mode = config.get("parse_mode", "HTML")

        bot_token = credentials.get("bot_token", "")
        base_url = f"https://api.telegram.org/bot{bot_token}/"

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=NoAuth(),
                provider_name="telegram",
            )
        else:
            # Override base_url to include the bot token
            http_client.base_url = base_url

        self.client = TelegramApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            if success:
                bot_info = self.client.get_me()
                bot_name = bot_info.get("username", "unknown")
                return ConnectionTestResult(
                    success=True,
                    message=f"Connected as @{bot_name}",
                    details=bot_info,
                )
            return ConnectionTestResult(success=False, message="Authentication failed")
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── MessagingPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single Telegram message."""
        try:
            # Raw API passthrough
            if message.extra and "raw_method" in message.extra:
                method = message.extra["raw_method"]
                payload = message.extra.get("raw_payload", {})
                response = self.client._call(method, **payload)
                return delivery_report_from_telegram(response, original_message_id=message.message_id)

            api_method, payload = build_payload(message, default_parse_mode=self._parse_mode)
            response = self.client._call(api_method, **payload)
            return delivery_report_from_telegram(response, original_message_id=message.message_id)
        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple Telegram messages sequentially.

        Telegram Bot API does not support batch sending.
        """
        return [self.send(message) for message in messages]
