"""
SMTP email adapter — implements MessagingPort.

This is the main entry point for the SMTP email integration.
Uses Python's smtplib directly, not ResilientHttpClient.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
)
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.providers.messaging.smtp.client import SMTPClient
from bapp_connectors.providers.messaging.smtp.manifest import manifest

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class SMTPMessagingAdapter(MessagingPort):
    """
    SMTP email adapter.

    Implements:
    - MessagingPort: send, send_bulk

    Note: This adapter uses smtplib directly. The http_client parameter is
    accepted for interface compatibility but not used.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, **kwargs):
        self.credentials = credentials

        host = credentials.get("host", "")
        # Derive host from username if not explicitly provided
        if not host and "@" in credentials.get("username", ""):
            host = credentials["username"].split("@")[1]

        self.client = SMTPClient(
            host=host,
            port=int(credentials.get("port", 587)),
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
            use_tls=str(credentials.get("use_tls", "true")).lower() == "true",
            use_ssl=str(credentials.get("use_ssl", "false")).lower() == "true",
            timeout=int(credentials.get("timeout", 30)),
            from_email=credentials.get("from_email", ""),
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
        """Send a single email message."""
        try:
            to_list = [message.to]
            cc = message.extra.get("cc", [])
            bcc = message.extra.get("bcc", [])

            # Parse attachments from extra
            attachments = []
            for att in message.attachments:
                attachments.append(
                    {
                        "filename": att.get("filename", "attachment"),
                        "content": att.get("content", b""),
                        "content_type": att.get("content_type", "application/octet-stream"),
                    }
                )

            success = self.client.send_email(
                to=to_list,
                subject=message.subject,
                body=message.body,
                html_body=message.html_body,
                from_email=message.extra.get("from_email", ""),
                cc=cc,
                bcc=bcc,
                attachments=attachments or None,
            )

            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.SENT if success else DeliveryStatus.FAILED,
            )
        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple email messages in bulk (sequentially)."""
        reports = []
        for message in messages:
            report = self.send(message)
            reports.append(report)
        return reports
