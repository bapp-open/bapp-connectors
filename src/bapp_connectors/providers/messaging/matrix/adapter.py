"""
Matrix messaging adapter — implements MessagingPort + RichMessagingCapability + WebhookCapability.

Uses the Matrix Client-Server API for sending messages and media.
Receives inbound messages via the Application Service (appservice) API.
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
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.matrix.client import MatrixApiClient
from bapp_connectors.providers.messaging.matrix.manifest import manifest
from bapp_connectors.providers.messaging.matrix.mappers import (
    build_payload,
    delivery_report_from_matrix,
    get_attachments_from_matrix,
    get_location_from_matrix,
    webhook_event_from_matrix,
)


class MatrixMessagingAdapter(MessagingPort, RichMessagingCapability, WebhookCapability):
    """
    Matrix messaging adapter.

    Implements:
    - MessagingPort: send, send_bulk
    - RichMessagingCapability: attachments, locations (inbound + outbound)
    - WebhookCapability: verify_webhook, parse_webhook (appservice API)
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._access_token = credentials.get("access_token", "")
        self._homeserver_url = credentials.get("homeserver_url", "").rstrip("/")
        self._appservice_token = credentials.get("appservice_token", "")
        self._default_room_id = config.get("default_room_id", "")

        base_url = f"{self._homeserver_url}/_matrix/client/v3/"

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BearerAuth(token=self._access_token),
                provider_name="matrix",
            )
        else:
            http_client.base_url = base_url
            http_client.auth = BearerAuth(token=self._access_token)

        self.client = MatrixApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            info = self.client.whoami()
            user_id = info.get("user_id", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected as {user_id}",
                details=info,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── MessagingPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a message to a Matrix room."""
        room_id = message.to or self._default_room_id
        if not room_id:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error="No room ID specified and no default_room_id configured",
            )

        try:
            content = build_payload(message)
            response = self.client.send_event(room_id, "m.room.message", content)
            return delivery_report_from_matrix(response, original_message_id=message.message_id)
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
        return get_attachments_from_matrix(message)

    def get_location(self, message: InboundMessage) -> MessageLocation | None:
        return get_location_from_matrix(message)

    def get_contacts(self, message: InboundMessage) -> list[MessageContact]:
        # Matrix has no native contact sharing; return empty
        return []

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify appservice webhook request.

        The homeserver authenticates to the appservice using the hs_token
        passed as a query parameter or Authorization header.
        """
        hs_token = secret or self._appservice_token
        if not hs_token:
            return True  # No token configured = skip verification

        # Check Authorization header (Bearer hs_token)
        auth_header = headers.get("Authorization") or headers.get("authorization", "")
        if auth_header:
            provided = auth_header.removeprefix("Bearer ").strip()
            return provided == hs_token

        return False

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse an appservice transaction or forwarded event."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise WebhookVerificationError(f"Invalid webhook payload: {exc}") from exc

        return webhook_event_from_matrix(data)
