"""
Gmail email adapter — implements EmailPort + InboxCapability.

Uses the Gmail REST API (v1) for both sending and reading email.
Authentication is via OAuth2 access token (refresh handled externally
by the Django layer).
"""

from __future__ import annotations

from datetime import datetime

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
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.providers.email.gmail.client import GmailApiClient
from bapp_connectors.providers.email.gmail.errors import classify_gmail_error
from bapp_connectors.providers.email.gmail.manifest import manifest
from bapp_connectors.providers.email.gmail.mappers import (
    _folder_to_label,
    gmail_attachment_to_content,
    gmail_message_to_detail,
    gmail_message_to_summary,
    gmail_send_to_report,
    outbound_to_raw_b64,
)


class GmailEmailAdapter(EmailPort, InboxCapability):
    """
    Gmail email adapter.

    Implements:
    - EmailPort: send, send_bulk
    - InboxCapability: fetch_messages, get_message, download_attachment
    """

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self._config = config or {}

        access_token = credentials.get("access_token", "")
        self._default_from_email = credentials.get("from_email", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(access_token),
                provider_name="gmail",
            )

        self.client = GmailApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            profile = self.client.get_profile()
            email = profile.get("emailAddress", "")
            total = profile.get("messagesTotal", 0)
            return ConnectionTestResult(
                success=True,
                message=f"Gmail: OK ({email}, {total} messages)",
                details={"email": email, "messages_total": total},
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── EmailPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single email via the Gmail API."""
        try:
            from_email = self._default_from_email
            raw_b64 = outbound_to_raw_b64(message, default_from_email=from_email)
            response = self.client.send_message(raw_b64)
            return gmail_send_to_report(response, message.message_id)
        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple emails sequentially."""
        return [self.send(message) for message in messages]

    # ── InboxCapability ──

    def fetch_messages(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        folder: str = "INBOX",
        limit: int = 50,
    ) -> list[EmailSummary]:
        """Fetch email summaries from a mailbox folder within a time window."""
        try:
            # Build Gmail search query
            query_parts: list[str] = []
            if since:
                query_parts.append(f"after:{since.strftime('%Y/%m/%d')}")
            if until:
                query_parts.append(f"before:{until.strftime('%Y/%m/%d')}")
            query = " ".join(query_parts)

            label_id = _folder_to_label(folder)

            result = self.client.list_messages(
                query=query,
                label_ids=[label_id],
                max_results=limit,
            )

            message_stubs = result.get("messages", [])
            if not message_stubs:
                return []

            # Fetch metadata for each message
            summaries: list[EmailSummary] = []
            for stub in message_stubs:
                msg = self.client.get_message(stub["id"], fmt="metadata")
                summaries.append(gmail_message_to_summary(msg, folder))

            return summaries

        except Exception as e:
            raise classify_gmail_error(e) from e

    def get_message(self, message_id: str, *, folder: str = "INBOX") -> EmailDetail:
        """Fetch the full structure of a single email."""
        try:
            msg = self.client.get_message(message_id, fmt="full")
            return gmail_message_to_detail(msg, folder)
        except Exception as e:
            raise classify_gmail_error(e) from e

    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        *,
        folder: str = "INBOX",
    ) -> EmailAttachmentContent:
        """Download a single attachment from an email."""
        try:
            # First get the message to find attachment metadata
            msg = self.client.get_message(message_id, fmt="full")
            detail = gmail_message_to_detail(msg, folder)

            # Find the attachment info
            att_info = None
            for att in detail.attachments:
                if att.attachment_id == attachment_id:
                    att_info = att
                    break

            if att_info is None:
                err_msg = f"Attachment {attachment_id} not found in message {message_id}"
                raise ValueError(err_msg)

            # Download the attachment data
            data = self.client.get_attachment(message_id, attachment_id)
            return gmail_attachment_to_content(
                data,
                attachment_id=attachment_id,
                filename=att_info.filename,
                content_type=att_info.content_type,
            )
        except Exception as e:
            raise classify_gmail_error(e) from e
