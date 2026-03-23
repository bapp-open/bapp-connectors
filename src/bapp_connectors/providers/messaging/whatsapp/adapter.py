"""
WhatsApp Cloud API messaging adapter — implements MessagingPort.

Uses Meta's WhatsApp Business Cloud API (Graph API) for sending
text, template, media, interactive, and location messages.
"""

from __future__ import annotations

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.whatsapp.client import WhatsAppApiClient
from bapp_connectors.providers.messaging.whatsapp.manifest import manifest
from bapp_connectors.providers.messaging.whatsapp.mappers import (
    build_payload,
    delivery_report_from_whatsapp,
)


class WhatsAppMessagingAdapter(MessagingPort):
    """
    WhatsApp Business Cloud API adapter.

    Implements:
    - MessagingPort: send, send_bulk

    Supports via OutboundMessage.extra:
    - Text messages (default)
    - Template messages (set template_id)
    - Media messages (set extra.media_type + extra.media_url or extra.media_id)
    - Raw payloads (set extra.raw_payload)
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self.phone_number_id = credentials.get("phone_number_id", "")

        api_version = config.get("api_version", "v21.0")
        base_url = f"https://graph.facebook.com/{api_version}/"

        if http_client is None:
            from bapp_connectors.core.http import BearerAuth

            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="whatsapp",
            )
        else:
            # Override base_url if api_version differs from manifest default
            http_client.base_url = base_url.rstrip("/") + "/"

        self.client = WhatsAppApiClient(
            http_client=http_client,
            phone_number_id=self.phone_number_id,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── MessagingPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single WhatsApp message."""
        try:
            # Allow raw payload passthrough
            if message.extra and "raw_payload" in message.extra:
                response = self.client.send_raw(message.extra["raw_payload"])
            else:
                payload = build_payload(message)
                response = self.client.send_raw(payload)

            return delivery_report_from_whatsapp(response, original_message_id=message.message_id)
        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple WhatsApp messages sequentially.

        WhatsApp Cloud API does not support batch sending — each message
        is sent individually.
        """
        return [self.send(message) for message in messages]
