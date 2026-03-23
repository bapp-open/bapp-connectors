"""
RoboSMS messaging adapter — implements MessagingPort.

This is the main entry point for the RoboSMS integration.
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
from bapp_connectors.providers.messaging.robosms.client import RoboSMSApiClient
from bapp_connectors.providers.messaging.robosms.manifest import manifest


class RoboSMSMessagingAdapter(MessagingPort):
    """
    RoboSMS messaging adapter.

    Implements:
    - MessagingPort: send, send_bulk
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.device_id = credentials.get("device_id", "")

        if http_client is None:
            from bapp_connectors.core.http import TokenAuth

            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=TokenAuth(credentials.get("token", ""), prefix="Token"),
                provider_name="robosms",
            )

        self.client = RoboSMSApiClient(
            http_client=http_client,
            device_id=self.device_id,
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
        """Send a single SMS message."""
        try:
            result = self.client.send_sms(
                to=message.to,
                content=message.body,
                device_id=message.extra.get("device_id"),
            )
            message_id = ""
            if isinstance(result, dict):
                message_id = str(result.get("id", ""))
            return DeliveryReport(
                message_id=message_id or message.message_id,
                status=DeliveryStatus.SENT,
            )
        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple SMS messages in bulk (sequentially)."""
        reports = []
        for message in messages:
            report = self.send(message)
            reports.append(report)
        return reports
