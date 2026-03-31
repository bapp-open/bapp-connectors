"""
Facebook Messenger adapter — implements MessagingPort + RichMessagingCapability + WebhookCapability.

Uses Meta's Send API via the Graph API for outbound messages.
Receives inbound messages via Meta's webhook (same X-Hub-Signature-256 as WhatsApp).
"""

from __future__ import annotations

import hashlib
import hmac
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
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.messenger.client import MessengerApiClient
from bapp_connectors.providers.messaging.messenger.manifest import manifest
from bapp_connectors.providers.messaging.messenger.mappers import (
    build_payload,
    delivery_report_from_messenger,
    get_attachments_from_messenger,
    get_location_from_messenger,
    webhook_event_from_messenger,
)


class MessengerMessagingAdapter(MessagingPort, RichMessagingCapability, WebhookCapability):
    """
    Facebook Messenger adapter.

    Implements:
    - MessagingPort: send, send_bulk
    - RichMessagingCapability: attachments, locations (inbound + outbound)
    - WebhookCapability: verify_webhook, parse_webhook, verify_challenge
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._page_access_token = credentials.get("page_access_token", "")
        self._page_id = credentials.get("page_id", "")
        self._app_secret = credentials.get("app_secret", "")
        self._webhook_verify_token = credentials.get("webhook_verify_token", "")

        api_version = config.get("api_version", "v21.0")
        base_url = f"https://graph.facebook.com/{api_version}/"

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BearerAuth(self._page_access_token),
                provider_name="messenger",
            )
        else:
            http_client.base_url = base_url.rstrip("/") + "/"
            http_client.auth = BearerAuth(self._page_access_token)

        self.client = MessengerApiClient(
            http_client=http_client,
            page_id=self._page_id,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            info = self.client.get_page_info()
            page_name = info.get("name", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to page: {page_name}",
                details=info,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── MessagingPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a message to a Messenger user (PSID)."""
        try:
            if message.extra and "raw_payload" in message.extra:
                response = self.client.send_raw(message.extra["raw_payload"])
            else:
                payload = build_payload(message)
                response = self.client.send_raw(payload)

            return delivery_report_from_messenger(response, original_message_id=message.message_id)
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
        return get_attachments_from_messenger(message)

    def get_location(self, message: InboundMessage) -> MessageLocation | None:
        return get_location_from_messenger(message)

    def get_contacts(self, message: InboundMessage) -> list[MessageContact]:
        # Messenger doesn't support contact sharing
        return []

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify Meta's X-Hub-Signature-256 HMAC signature."""
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

        return webhook_event_from_messenger(data)

    def verify_challenge(self, params: dict) -> str | None:
        """Handle Meta's GET verification challenge.

        Meta sends: GET ?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>
        """
        mode = params.get("hub.mode", "")
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")

        if mode == "subscribe" and token == self._webhook_verify_token:
            return challenge
        return None
