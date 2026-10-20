"""
BAPP ERP adapter — implements ErpPort and MessagingPort (SMS through the ERP's phones).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
)
from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ErpPort, MessagingPort
from bapp_connectors.providers.erp.bapp.client import BappErpApiClient
from bapp_connectors.providers.erp.bapp.manifest import ALLOWED_HOST, manifest


def base_url_error(base_url: str) -> str:
    """Why ``base_url`` may not carry the token, or "" when it may.

    The token is a BAPP user token: it only goes over https to bapp.ro or a subdomain of it.
    """
    try:
        parts = urlsplit(base_url or "")
        host = (parts.hostname or "").lower()
    except ValueError:
        return "API URL invalid"
    if parts.scheme != "https":
        return "API URL trebuie sa fie https"
    if host != ALLOWED_HOST and not host.endswith("." + ALLOWED_HOST):
        return f"API URL trebuie sa fie pe {ALLOWED_HOST}"
    return ""


class BappErpAdapter(ErpPort, MessagingPort):
    """
    BAPP ERP adapter.

    Implements:
    - ErpPort: get_capabilities, print_file, send_sms
    - MessagingPort: send, send_bulk (an SMS through the ERP)
    """

    manifest = manifest

    def __init__(
        self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs
    ):
        self.credentials = credentials
        config = config or {}
        base_url = config.get("base_url") or self.manifest.base_url
        # checked here, raised on use: building the adapter (listing, schema) must not break
        self._base_url_error = base_url_error(base_url)

        if http_client is None:
            http_client = ResilientHttpClient(base_url=base_url, provider_name="bapp")

        self.client = BappErpApiClient(
            http_client=http_client,
            token=credentials.get("token", ""),
            tenant_id=credentials.get("tenant_id", ""),
            base_url=base_url,
        )

    def __repr__(self) -> str:
        return f"BappErpAdapter(client={self.client!r})"

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            capabilities = self.get_capabilities()
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))
        return ConnectionTestResult(
            success=True, message="Connection successful", details={"capabilities": capabilities}
        )

    # ── ErpPort ──

    def _ensure_base_url(self) -> None:
        if self._base_url_error:
            raise ConfigurationError(self._base_url_error)

    def get_capabilities(self) -> dict:
        self._ensure_base_url()
        return self.client.get_capabilities()

    def print_file(self, url: str, device: str = "", printer: str = "", copies: int = 1) -> dict:
        self._ensure_base_url()
        return self.client.print_file(url, device, printer, copies)

    def send_sms(self, recipients: list[str], body: str, phone: str = "") -> dict:
        self._ensure_base_url()
        return self.client.send_sms(recipients, body, phone)

    # ── MessagingPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send one SMS. The ERP queues it on a phone; delivery is not confirmed here."""
        try:
            self.send_sms([message.to], message.body, phone=message.extra.get("phone", ""))
        except Exception as e:
            return DeliveryReport(message_id=message.message_id, status=DeliveryStatus.FAILED, error=str(e))
        return DeliveryReport(message_id=message.message_id, status=DeliveryStatus.QUEUED)

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        return [self.send(m) for m in messages]
