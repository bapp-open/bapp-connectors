"""
Unit tests for SMTP InboxCapability (IMAP-based email reading).

Tests the mapper logic and adapter orchestration with mocked IMAP client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from unittest.mock import MagicMock, patch

import pytest

from bapp_connectors.core.capabilities import InboxCapability
from bapp_connectors.core.dto import (
    EmailAttachmentContent,
    EmailDetail,
    EmailSummary,
)
from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter
from bapp_connectors.providers.email.smtp.mappers import (
    extract_attachment_content,
    headers_to_summary,
    message_to_detail,
)

# ── Helpers ──


def _build_mime_message(
    *,
    subject: str = "Test Subject",
    from_addr: str = "sender@example.com",
    from_name: str = "Sender Name",
    to_addr: str = "recipient@example.com",
    body: str = "Plain text body",
    html_body: str = "",
    attachments: list[tuple[str, bytes, str]] | None = None,
    date: datetime | None = None,
    in_reply_to: str = "",
    cc: str = "",
) -> MIMEMultipart:
    """Build a realistic MIME email for testing."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True) if date is None else formatdate(date.timestamp(), localtime=False)
    if cc:
        msg["Cc"] = cc
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to

    # Text parts
    alt = MIMEMultipart("alternative")
    if body:
        alt.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    # Attachments
    if attachments:
        for filename, content, content_type in attachments:
            part = MIMEBase(*content_type.split("/", 1))
            part.set_payload(content)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

    return msg


def _make_adapter(*, with_imap: bool = True) -> SMTPEmailAdapter:
    """Create an adapter with optionally mocked IMAP client."""
    creds = {
        "host": "smtp.example.com",
        "port": "587",
        "username": "user@example.com",
        "password": "secret",
        "use_tls": "true",
        "use_ssl": "false",
    }
    if with_imap:
        creds["imap_host"] = "imap.example.com"
        creds["imap_port"] = "993"
        creds["imap_use_ssl"] = "true"

    with patch("bapp_connectors.providers.email.smtp.adapter.SMTPClient"):
        adapter = SMTPEmailAdapter(credentials=creds)

    return adapter


# ── Capability Declaration Tests ──


class TestInboxCapabilityDeclaration:

    def test_adapter_implements_inbox_capability(self):
        adapter = _make_adapter()
        assert isinstance(adapter, InboxCapability)

    def test_supports_inbox_capability(self):
        adapter = _make_adapter()
        assert adapter.supports(InboxCapability)

    def test_manifest_declares_inbox_capability(self):
        from bapp_connectors.providers.email.smtp.manifest import manifest

        assert InboxCapability in manifest.capabilities

    def test_no_imap_client_without_credentials(self):
        creds = {
            "host": "",
            "port": "587",
            "username": "",
            "password": "",
            "use_tls": "false",
            "use_ssl": "false",
        }
        with patch("bapp_connectors.providers.email.smtp.adapter.SMTPClient"):
            adapter = SMTPEmailAdapter(credentials=creds)
        assert adapter.imap_client is None

    def test_imap_host_defaults_to_smtp_host(self):
        creds = {
            "host": "mail.example.com",
            "port": "587",
            "username": "user@example.com",
            "password": "secret",
            "use_tls": "true",
            "use_ssl": "false",
        }
        with patch("bapp_connectors.providers.email.smtp.adapter.SMTPClient"):
            adapter = SMTPEmailAdapter(credentials=creds)
        assert adapter.imap_client is not None
        assert adapter.imap_client.host == "mail.example.com"


# ── Mapper Tests ──


class TestHeadersToSummary:

    def test_basic_fields(self):
        msg = _build_mime_message(
            subject="Hello World",
            from_addr="alice@example.com",
            from_name="Alice",
            to_addr="bob@example.com",
        )
        summary = headers_to_summary("123", msg, set(), "INBOX")
        assert summary.message_id == "123"
        assert summary.subject == "Hello World"
        assert summary.sender.address == "alice@example.com"
        assert summary.sender.name == "Alice"
        assert summary.folder == "INBOX"
        assert len(summary.to) == 1
        assert summary.to[0].address == "bob@example.com"

    def test_seen_flag_sets_is_read(self):
        msg = _build_mime_message()
        summary = headers_to_summary("1", msg, {"\\Seen"}, "INBOX")
        assert summary.is_read is True

    def test_unseen_is_not_read(self):
        msg = _build_mime_message()
        summary = headers_to_summary("1", msg, set(), "INBOX")
        assert summary.is_read is False

    def test_flagged(self):
        msg = _build_mime_message()
        summary = headers_to_summary("1", msg, {"\\Flagged"}, "INBOX")
        assert summary.is_flagged is True

    def test_has_attachments(self):
        msg = _build_mime_message(attachments=[("file.txt", b"data", "text/plain")])
        summary = headers_to_summary("1", msg, set(), "INBOX", has_attachments=True)
        assert summary.has_attachments is True

    def test_no_attachments(self):
        msg = _build_mime_message()
        summary = headers_to_summary("1", msg, set(), "INBOX", has_attachments=False)
        assert summary.has_attachments is False


class TestMessageToDetail:

    def test_basic_fields(self):
        msg = _build_mime_message(
            subject="Detail Test",
            from_addr="sender@test.com",
            to_addr="recip@test.com",
            body="Hello plain",
            html_body="<b>Hello HTML</b>",
        )
        detail = message_to_detail("42", msg, "INBOX")
        assert detail.message_id == "42"
        assert detail.subject == "Detail Test"
        assert detail.text_body == "Hello plain"
        assert detail.html_body == "<b>Hello HTML</b>"
        assert detail.sender.address == "sender@test.com"

    def test_cc_parsing(self):
        msg = _build_mime_message(cc="cc1@test.com, cc2@test.com")
        detail = message_to_detail("1", msg, "INBOX")
        assert len(detail.cc) == 2
        assert detail.cc[0].address == "cc1@test.com"

    def test_in_reply_to(self):
        msg = _build_mime_message(in_reply_to="<original-msg-id@test.com>")
        detail = message_to_detail("1", msg, "INBOX")
        assert detail.in_reply_to == "<original-msg-id@test.com>"

    def test_attachment_metadata(self):
        msg = _build_mime_message(
            attachments=[
                ("report.pdf", b"%PDF-content", "application/pdf"),
                ("image.png", b"\x89PNG", "image/png"),
            ],
        )
        detail = message_to_detail("1", msg, "INBOX")
        assert len(detail.attachments) == 2
        assert detail.attachments[0].filename == "report.pdf"
        assert detail.attachments[0].content_type == "application/pdf"
        assert detail.attachments[0].size == len(b"%PDF-content")
        assert detail.attachments[1].filename == "image.png"

    def test_headers_captured(self):
        msg = _build_mime_message(subject="Headers Test")
        detail = message_to_detail("1", msg, "INBOX")
        assert "Subject" in detail.headers
        assert detail.headers["Subject"] == "Headers Test"


class TestExtractAttachmentContent:

    def test_extracts_correct_attachment(self):
        msg = _build_mime_message(
            attachments=[
                ("file1.txt", b"content1", "text/plain"),
                ("file2.pdf", b"content2", "application/pdf"),
            ],
        )
        # Get attachment IDs from detail
        detail = message_to_detail("1", msg, "INBOX")
        att_id = detail.attachments[1].attachment_id

        result = extract_attachment_content("1", att_id, msg)
        assert result is not None
        assert result.filename == "file2.pdf"
        assert result.content == b"content2"
        assert result.content_type == "application/pdf"

    def test_returns_none_for_unknown_id(self):
        msg = _build_mime_message(
            attachments=[("file.txt", b"data", "text/plain")],
        )
        result = extract_attachment_content("1", "nonexistent", msg)
        assert result is None


# ── Adapter Orchestration Tests ──


class TestAdapterFetchMessages:

    def test_fetch_messages_calls_imap(self):
        adapter = _make_adapter()
        mock_imap = MagicMock()
        adapter.imap_client = mock_imap

        mock_imap.fetch_uids.return_value = ["10", "11"]
        msg = _build_mime_message(subject="Msg 1")
        mock_imap.fetch_headers.return_value = [
            ("10", msg, {"\\Seen"}, False),
            ("11", msg, set(), True),
        ]

        results = adapter.fetch_messages(folder="INBOX", limit=10)
        assert len(results) == 2
        assert all(isinstance(r, EmailSummary) for r in results)
        mock_imap.fetch_uids.assert_called_once()

    def test_fetch_messages_empty(self):
        adapter = _make_adapter()
        mock_imap = MagicMock()
        adapter.imap_client = mock_imap
        mock_imap.fetch_uids.return_value = []

        results = adapter.fetch_messages()
        assert results == []

    def test_fetch_messages_with_date_range(self):
        adapter = _make_adapter()
        mock_imap = MagicMock()
        adapter.imap_client = mock_imap
        mock_imap.fetch_uids.return_value = []

        since = datetime(2024, 1, 1, tzinfo=UTC)
        until = datetime(2024, 1, 31, tzinfo=UTC)
        adapter.fetch_messages(since=since, until=until)

        mock_imap.fetch_uids.assert_called_once_with(
            since=since, until=until, folder="INBOX", limit=50,
        )


class TestAdapterGetMessage:

    def test_get_message_returns_detail(self):
        adapter = _make_adapter()
        mock_imap = MagicMock()
        adapter.imap_client = mock_imap

        msg = _build_mime_message(subject="Full Message", body="Body text")
        mock_imap.fetch_message.return_value = msg

        detail = adapter.get_message("42", folder="Sent")
        assert isinstance(detail, EmailDetail)
        assert detail.message_id == "42"
        assert detail.folder == "Sent"
        assert detail.subject == "Full Message"
        assert detail.text_body == "Body text"


class TestAdapterDownloadAttachment:

    def test_download_attachment(self):
        adapter = _make_adapter()
        mock_imap = MagicMock()
        adapter.imap_client = mock_imap

        msg = _build_mime_message(
            attachments=[("doc.pdf", b"pdf-bytes", "application/pdf")],
        )
        mock_imap.fetch_message.return_value = msg

        # Get the attachment ID
        detail = message_to_detail("5", msg, "INBOX")
        att_id = detail.attachments[0].attachment_id

        result = adapter.download_attachment("5", att_id)
        assert isinstance(result, EmailAttachmentContent)
        assert result.content == b"pdf-bytes"

    def test_download_nonexistent_attachment_raises(self):
        adapter = _make_adapter()
        mock_imap = MagicMock()
        adapter.imap_client = mock_imap

        msg = _build_mime_message()
        mock_imap.fetch_message.return_value = msg

        with pytest.raises(Exception, match="not found"):
            adapter.download_attachment("1", "bad-id")


class TestAdapterRequiresIMAP:

    def test_fetch_messages_raises_without_imap(self):
        adapter = _make_adapter()
        adapter.imap_client = None

        with pytest.raises(Exception, match="IMAP"):
            adapter.fetch_messages()

    def test_get_message_raises_without_imap(self):
        adapter = _make_adapter()
        adapter.imap_client = None

        with pytest.raises(Exception, match="IMAP"):
            adapter.get_message("1")

    def test_download_attachment_raises_without_imap(self):
        adapter = _make_adapter()
        adapter.imap_client = None

        with pytest.raises(Exception, match="IMAP"):
            adapter.download_attachment("1", "att-1")
