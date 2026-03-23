"""
GoIP SMS gateway adapter — implements MessagingPort.

GoIP is a physical GSM gateway device that sends SMS over a cellular network.
Communicates via a simple HTTP interface exposed by the device.
"""

from __future__ import annotations

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
)
from bapp_connectors.core.http import BasicAuth, ResilientHttpClient
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.goip.client import GoIPApiClient
from bapp_connectors.providers.messaging.goip.manifest import manifest


class GoIPMessagingAdapter(MessagingPort):
    """
    GoIP GSM gateway adapter.

    Implements:
    - MessagingPort: send, send_bulk (reply inherited from MessagingPort)
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        username = credentials.get("username", "")
        password = credentials.get("password", "")
        ip = credentials.get("ip", "")
        line = config.get("line", 1)
        max_retries = config.get("max_retries", 0)

        base_url = config.get("base_url") or f"http://{ip}/default/en_US/"

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BasicAuth(username=username, password=password),
                provider_name="goip",
            )
        else:
            http_client.base_url = base_url.rstrip("/") + "/"

        self.client = GoIPApiClient(
            http_client=http_client,
            username=username,
            password=password,
            line=line,
            max_retries=max_retries,
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
                message="Device reachable" if success else "Device unreachable or auth failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── MessagingPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single SMS via the GoIP device."""
        try:
            line = message.extra.get("line") if message.extra else None
            success = self.client.send_sms(to=message.to, message=message.body, line=line)
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.SENT if success else DeliveryStatus.FAILED,
                error="" if success else "Line busy after max retries",
            )
        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple SMS messages sequentially via the GoIP device."""
        return [self.send(message) for message in messages]
