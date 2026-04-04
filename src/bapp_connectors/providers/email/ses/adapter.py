"""
Amazon SES email adapter — implements EmailPort.

Uses boto3 SES v2 for sending email. Supports simple text/HTML emails
and raw MIME messages with attachments.

Requires the `boto3` package (pip install boto3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
)
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.providers.email.ses.client import SESClient
from bapp_connectors.providers.email.ses.errors import classify_ses_error
from bapp_connectors.providers.email.ses.manifest import manifest
from bapp_connectors.providers.email.ses.mappers import (
    outbound_to_raw_mime,
    outbound_to_ses_kwargs,
    ses_response_to_report,
)

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class SESEmailAdapter(EmailPort):
    """
    Amazon SES email adapter.

    Implements:
    - EmailPort: send, send_bulk

    Note: This adapter uses boto3 directly. The http_client parameter is
    accepted for interface compatibility but not used.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._from_email = credentials.get("from_email", "")

        self.client = SESClient(
            access_key_id=credentials.get("access_key_id", ""),
            secret_access_key=credentials.get("secret_access_key", ""),
            region=config.get("region", "us-east-1"),
            configuration_set=config.get("configuration_set", ""),
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
                message="Connected to Amazon SES" if success else "SES authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── EmailPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single email via SES."""
        try:
            if message.attachments:
                # Raw MIME path for messages with attachments
                raw_mime = outbound_to_raw_mime(message, self._from_email)
                from_email = message.extra.get("from_email", "") or self._from_email
                response = self.client.send_raw_email(
                    from_email=from_email,
                    raw_message=raw_mime,
                )
            else:
                # Simple path for text/HTML emails
                kwargs = outbound_to_ses_kwargs(message, self._from_email)
                response = self.client.send_simple_email(**kwargs)

            return ses_response_to_report(response, message.message_id)

        except Exception as e:
            error = classify_ses_error(e)
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(error),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple emails sequentially."""
        reports = []
        for message in messages:
            report = self.send(message)
            reports.append(report)
        return reports
