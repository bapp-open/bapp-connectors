"""
Discord Bot API adapter — implements MessagingPort + RichMessagingCapability + WebhookCapability.

Uses Discord REST API v10 for sending messages, embeds, and media.
Receives events via interaction webhooks (Ed25519 signature verification).
"""

from __future__ import annotations

import json

from bapp_connectors.core.capabilities import RichMessagingCapability, WebhookCapability
from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    InboundMessage,
    MessageAttachment,
    MessageContact,
    MessageLocation,
    OutboundMessage,
    WebhookEvent,
)
from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.http.auth import TokenAuth
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.discord.client import DiscordApiClient
from bapp_connectors.providers.messaging.discord.manifest import manifest
from bapp_connectors.providers.messaging.discord.mappers import (
    build_payload,
    delivery_report_from_discord,
    get_attachments_from_discord,
    webhook_event_from_discord,
)


class DiscordMessagingAdapter(MessagingPort, RichMessagingCapability, WebhookCapability):
    """
    Discord Bot API adapter.

    Implements:
    - MessagingPort: send, send_bulk
    - RichMessagingCapability: attachments (inbound + outbound)
    - WebhookCapability: Ed25519 signature verification, interaction/event parsing
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._bot_token = credentials.get("bot_token", "")
        self._application_id = credentials.get("application_id", "")
        self._public_key = credentials.get("public_key", "")
        self._default_channel_id = config.get("default_channel_id", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=TokenAuth(token=self._bot_token, prefix="Bot"),
                provider_name="discord",
            )
        else:
            http_client.auth = TokenAuth(token=self._bot_token, prefix="Bot")

        self.client = DiscordApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            user = self.client.get_current_user()
            username = user.get("username", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected as {username}",
                details=user,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── MessagingPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a message to a Discord channel."""
        channel_id = message.to or self._default_channel_id
        if not channel_id:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error="No channel ID specified and no default_channel_id configured",
            )

        try:
            payload = build_payload(message)
            response = self.client.send_message(
                channel_id=channel_id,
                content=payload.get("content", ""),
                embeds=payload.get("embeds"),
                message_reference=payload.get("message_reference"),
            )
            return delivery_report_from_discord(response, original_message_id=message.message_id)
        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple messages sequentially."""
        return [self.send(message) for message in messages]

    # ── RichMessagingCapability ──

    def get_attachments(self, message: InboundMessage) -> list[MessageAttachment]:
        return get_attachments_from_discord(message)

    def get_location(self, message: InboundMessage) -> MessageLocation | None:
        # Discord has no native location sharing
        return None

    def get_contacts(self, message: InboundMessage) -> list[MessageContact]:
        # Discord has no native contact sharing
        return []

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify Discord interaction webhook Ed25519 signature.

        Discord sends X-Signature-Ed25519 and X-Signature-Timestamp headers.
        The signed content is: timestamp + body.
        """
        public_key = secret or self._public_key
        if not public_key:
            return False

        signature = headers.get("X-Signature-Ed25519") or headers.get("x-signature-ed25519", "")
        timestamp = headers.get("X-Signature-Timestamp") or headers.get("x-signature-timestamp", "")

        if not signature or not timestamp:
            return False

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
            key.verify(bytes.fromhex(signature), timestamp.encode() + body)
            return True
        except ImportError:
            # cryptography not installed — cannot verify
            return False
        except Exception:
            return False

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse a Discord interaction or gateway event."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise WebhookVerificationError(f"Invalid webhook payload: {exc}") from exc

        return webhook_event_from_discord(data)
