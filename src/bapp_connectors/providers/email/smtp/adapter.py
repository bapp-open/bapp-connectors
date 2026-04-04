"""
SMTP email adapter — implements EmailPort + InboxCapability.

This is the main entry point for the SMTP email integration.
Uses Python's smtplib for sending and imaplib for inbox reading.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import InboxCapability
from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    EmailAttachmentContent,
    EmailDetail,
    EmailSummary,
    OutboundMessage,
)
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.providers.email.smtp.client import IMAPClient, SMTPClient
from bapp_connectors.providers.email.smtp.errors import classify_imap_error
from bapp_connectors.providers.email.smtp.manifest import manifest
from bapp_connectors.providers.email.smtp.mappers import (
    extract_attachment_content,
    headers_to_summary,
    message_to_detail,
)

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class SMTPEmailAdapter(EmailPort, InboxCapability):
    """
    SMTP email adapter.

    Implements:
    - EmailPort: send, send_bulk
    - InboxCapability: fetch_messages, get_message, download_attachment (requires IMAP credentials)

    Note: This adapter uses smtplib/imaplib directly. The http_client parameter
    is accepted for interface compatibility but not used.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
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

        # IMAP client — only created if IMAP credentials are provided
        imap_host = credentials.get("imap_host", "") or host
        if imap_host:
            self.imap_client: IMAPClient | None = IMAPClient(
                host=imap_host,
                port=int(credentials.get("imap_port", 993)),
                username=credentials.get("username", ""),
                password=credentials.get("password", ""),
                use_ssl=str(credentials.get("imap_use_ssl", "true")).lower() == "true",
                timeout=int(credentials.get("timeout", 30)),
            )
        else:
            self.imap_client = None

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            smtp_ok = self.client.test_auth()
            if not smtp_ok:
                return ConnectionTestResult(success=False, message="SMTP authentication failed")

            imap_msg = ""
            if self.imap_client:
                imap_ok = self.imap_client.test_auth()
                imap_msg = " | IMAP: OK" if imap_ok else " | IMAP: authentication failed"

            return ConnectionTestResult(
                success=True,
                message=f"SMTP: OK{imap_msg}",
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

    # ── InboxCapability ──

    def _require_imap(self) -> IMAPClient:
        """Return the IMAP client or raise if inbox is not configured."""
        if self.imap_client is None:
            msg = "Inbox capabilities require IMAP credentials (imap_host)"
            raise classify_imap_error(ValueError(msg))
        return self.imap_client

    def fetch_messages(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        folder: str = "INBOX",
        limit: int = 50,
    ) -> list[EmailSummary]:
        """Fetch email summaries from a mailbox folder within a time window."""
        imap = self._require_imap()
        try:
            uids = imap.fetch_uids(since=since, until=until, folder=folder, limit=limit)
            if not uids:
                return []

            header_results = imap.fetch_headers(uids, folder=folder)
            return [
                headers_to_summary(uid, msg, flags, folder, has_attachments=has_att)
                for uid, msg, flags, has_att in header_results
            ]
        except Exception as e:
            raise classify_imap_error(e) from e

    def get_message(self, message_id: str, *, folder: str = "INBOX") -> EmailDetail:
        """Fetch the full structure of a single email."""
        imap = self._require_imap()
        try:
            msg = imap.fetch_message(message_id, folder=folder)
            return message_to_detail(message_id, msg, folder)
        except Exception as e:
            raise classify_imap_error(e) from e

    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        *,
        folder: str = "INBOX",
    ) -> EmailAttachmentContent:
        """Download a single attachment from an email."""
        imap = self._require_imap()
        try:
            msg = imap.fetch_message(message_id, folder=folder)
            result = extract_attachment_content(message_id, attachment_id, msg)
            if result is None:
                msg_text = f"Attachment {attachment_id} not found in message {message_id}"
                raise ValueError(msg_text)
            return result
        except Exception as e:
            raise classify_imap_error(e) from e
