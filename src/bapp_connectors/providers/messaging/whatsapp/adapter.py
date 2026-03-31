"""
WhatsApp Cloud API messaging adapter — implements MessagingPort + WebhookCapability.

Uses Meta's WhatsApp Business Cloud API (Graph API) for sending
text, template, media, interactive, and location messages.
Receives inbound messages and status updates via webhooks.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from bapp_connectors.core.capabilities import WebhookCapability
from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
    WebhookEvent,
)
from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.whatsapp.client import WhatsAppApiClient
from bapp_connectors.providers.messaging.whatsapp.manifest import manifest
from bapp_connectors.providers.messaging.whatsapp.mappers import (
    build_payload,
    delivery_report_from_whatsapp,
    webhook_event_from_whatsapp,
)


class WhatsAppMessagingAdapter(MessagingPort, WebhookCapability):
    """
    WhatsApp Business Cloud API adapter.

    Implements:
    - MessagingPort: send, send_bulk
    - WebhookCapability: verify_webhook, parse_webhook, verify_challenge

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
        self._app_secret = credentials.get("app_secret", "")
        self._webhook_verify_token = credentials.get("webhook_verify_token", "")

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

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify Meta's X-Hub-Signature-256 HMAC signature on webhook POSTs."""
        app_secret = secret or self._app_secret
        if not app_secret:
            return False

        sig_header = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256", "")
        if not sig_header:
            return False

        expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        actual = sig_header.removeprefix("sha256=").strip()
        return hmac.compare_digest(expected, actual)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse a Meta webhook payload into a normalized WebhookEvent."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise WebhookVerificationError(f"Invalid webhook payload: {exc}") from exc

        return webhook_event_from_whatsapp(data)

    def verify_challenge(self, params: dict) -> str | None:
        """Handle Meta's GET verification challenge when registering a webhook URL.

        Meta sends: GET ?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>
        Return the challenge string if the verify token matches, None otherwise.
        """
        mode = params.get("hub.mode", "")
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")

        if mode == "subscribe" and token == self._webhook_verify_token:
            return challenge
        return None
