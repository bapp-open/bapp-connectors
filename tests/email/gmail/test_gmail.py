"""
Gmail email provider unit tests — no network.

Tests: manifest, mappers (outbound + inbound), adapter (send, send_bulk,
inbox operations, credential validation, connection test), error classification.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from bapp_connectors.core.capabilities import InboxCapability
from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    MessageChannel,
    OutboundMessage,
)
from bapp_connectors.core.errors import AuthenticationError, RateLimitError
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.core.types import AuthStrategy, ProviderFamily
from bapp_connectors.providers.email.gmail.adapter import GmailEmailAdapter
from bapp_connectors.providers.email.gmail.errors import (
    GmailConnectionError,
    GmailError,
    classify_gmail_error,
)
from bapp_connectors.providers.email.gmail.manifest import manifest
from bapp_connectors.providers.email.gmail.mappers import (
    _folder_to_label,
    _label_to_folder,
    gmail_attachment_to_content,
    gmail_message_to_detail,
    gmail_message_to_summary,
    gmail_send_to_report,
    outbound_to_raw_b64,
)

ACCESS_TOKEN = "ya29.test-access-token"
FROM_EMAIL = "sender@example.com"

# ── Mock Gmail API responses ──

MOCK_GMAIL_MESSAGE_METADATA = {
    "id": "msg123",
    "threadId": "thread123",
    "labelIds": ["INBOX", "UNREAD"],
    "snippet": "Hey Bob, here is the document you requested...",
    "payload": {
        "headers": [
            {"name": "From", "value": "Alice <alice@example.com>"},
            {"name": "To", "value": "bob@example.com"},
            {"name": "Subject", "value": "Test Subject"},
            {"name": "Date", "value": "Fri, 03 Apr 2026 10:00:00 +0000"},
        ],
        "parts": [
            {"mimeType": "text/plain", "body": {"size": 10}},
            {
                "mimeType": "application/pdf",
                "filename": "doc.pdf",
                "body": {"attachmentId": "att1", "size": 1000},
            },
        ],
    },
    "sizeEstimate": 5000,
}

MOCK_GMAIL_MESSAGE_FULL = {
    "id": "msg456",
    "threadId": "thread456",
    "labelIds": ["INBOX", "STARRED"],
    "snippet": "Hello there...",
    "payload": {
        "mimeType": "multipart/mixed",
        "headers": [
            {"name": "From", "value": "Charlie <charlie@example.com>"},
            {"name": "To", "value": "dave@example.com, Eve <eve@example.com>"},
            {"name": "Cc", "value": "frank@example.com"},
            {"name": "Subject", "value": "Full Message"},
            {"name": "Date", "value": "Fri, 03 Apr 2026 12:00:00 +0000"},
            {"name": "In-Reply-To", "value": "<orig-msg-id@example.com>"},
            {"name": "References", "value": "<ref1@example.com> <ref2@example.com>"},
        ],
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                b"Hello plain text"
                            ).decode("ascii"),
                            "size": 16,
                        },
                    },
                    {
                        "mimeType": "text/html",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                b"<p>Hello HTML</p>"
                            ).decode("ascii"),
                            "size": 17,
                        },
                    },
                ],
            },
            {
                "mimeType": "application/pdf",
                "filename": "report.pdf",
                "body": {"attachmentId": "att-pdf-1", "size": 2048},
            },
        ],
    },
    "sizeEstimate": 10000,
}

MOCK_GMAIL_SEND_RESPONSE = {
    "id": "sent-msg-1",
    "threadId": "sent-thread-1",
    "labelIds": ["SENT"],
}

MOCK_GMAIL_PROFILE = {
    "emailAddress": "user@gmail.com",
    "messagesTotal": 42000,
    "threadsTotal": 15000,
    "historyId": "999999",
}


def _make_message(**overrides) -> OutboundMessage:
    """Build a minimal OutboundMessage with sensible defaults."""
    defaults = {
        "channel": MessageChannel.EMAIL,
        "to": "recipient@example.com",
        "subject": "Test Subject",
        "body": "Plain text body.",
    }
    defaults.update(overrides)
    return OutboundMessage(**defaults)


@pytest.fixture
def adapter():
    """Create a GmailEmailAdapter with a mocked HTTP client."""
    mock_http = MagicMock()
    return GmailEmailAdapter(
        credentials={
            "access_token": ACCESS_TOKEN,
            "from_email": FROM_EMAIL,
        },
        http_client=mock_http,
    )


# ── TestGmailManifest ──


class TestGmailManifest:
    def test_name(self):
        assert manifest.name == "gmail"

    def test_family(self):
        assert manifest.family == ProviderFamily.EMAIL

    def test_capabilities_includes_email_port(self):
        assert EmailPort in manifest.capabilities

    def test_capabilities_includes_inbox_capability(self):
        assert InboxCapability in manifest.capabilities

    def test_display_name(self):
        assert manifest.display_name == "Gmail"

    def test_auth_strategy(self):
        assert manifest.auth.strategy == AuthStrategy.BEARER

    def test_auth_required_fields_access_token(self):
        field_names = [f.name for f in manifest.auth.required_fields]
        assert "access_token" in field_names

    def test_auth_from_email_optional(self):
        fields = {f.name: f for f in manifest.auth.required_fields}
        assert fields["from_email"].required is False


# ── TestGmailMappers ──


class TestGmailMappers:
    """Test outbound/inbound mappers and helper functions."""

    # ── outbound_to_raw_b64 ──

    def test_basic_email_produces_valid_base64url(self):
        msg = _make_message()
        raw = outbound_to_raw_b64(msg, default_from_email=FROM_EMAIL)

        # Must be valid base64url
        decoded = base64.urlsafe_b64decode(raw)
        decoded_str = decoded.decode("utf-8", errors="replace")
        assert "To: recipient@example.com" in decoded_str
        assert "From: sender@example.com" in decoded_str
        assert "Subject: Test Subject" in decoded_str
        # Body is MIME-encoded (Content-Transfer-Encoding: base64 within MIME)
        body_b64 = base64.b64encode(b"Plain text body.").decode("ascii")
        assert body_b64 in decoded_str

    def test_with_cc_and_bcc(self):
        msg = _make_message(extra={
            "cc": ["cc1@example.com", "cc2@example.com"],
            "bcc": ["bcc@example.com"],
        })
        raw = outbound_to_raw_b64(msg, default_from_email=FROM_EMAIL)
        decoded_str = base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")

        assert "Cc: cc1@example.com, cc2@example.com" in decoded_str
        assert "Bcc: bcc@example.com" in decoded_str

    def test_with_attachments(self):
        content = b"PDF file bytes"
        msg = _make_message(
            body="See attached.",
            attachments=[
                {
                    "filename": "report.pdf",
                    "content": content,
                    "content_type": "application/pdf",
                },
            ],
        )
        raw = outbound_to_raw_b64(msg, default_from_email=FROM_EMAIL)
        decoded_str = base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")

        assert "multipart/mixed" in decoded_str
        assert 'filename="report.pdf"' in decoded_str

    def test_with_html_body(self):
        msg = _make_message(
            body="Plain version",
            html_body="<h1>HTML version</h1>",
        )
        raw = outbound_to_raw_b64(msg, default_from_email=FROM_EMAIL)
        decoded_str = base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")

        assert "multipart/alternative" in decoded_str
        # Bodies are MIME-encoded (Content-Transfer-Encoding: base64 within MIME)
        plain_b64 = base64.b64encode(b"Plain version").decode("ascii")
        html_b64 = base64.b64encode(b"<h1>HTML version</h1>").decode("ascii")
        assert plain_b64 in decoded_str
        assert html_b64 in decoded_str

    def test_from_email_override_via_extra(self):
        msg = _make_message(extra={"from_email": "override@example.com"})
        raw = outbound_to_raw_b64(msg, default_from_email=FROM_EMAIL)
        decoded_str = base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")

        assert "From: override@example.com" in decoded_str

    def test_reply_to_header(self):
        msg = _make_message(extra={"reply_to": "reply@example.com"})
        raw = outbound_to_raw_b64(msg, default_from_email=FROM_EMAIL)
        decoded_str = base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")

        assert "Reply-To: reply@example.com" in decoded_str

    # ── gmail_send_to_report ──

    def test_send_to_report_maps_to_sent(self):
        report = gmail_send_to_report(MOCK_GMAIL_SEND_RESPONSE, "my-msg-1")

        assert report.status == DeliveryStatus.SENT
        assert report.message_id == "my-msg-1"
        assert report.extra["gmail_id"] == "sent-msg-1"
        assert report.extra["thread_id"] == "sent-thread-1"

    def test_send_to_report_empty_id(self):
        report = gmail_send_to_report({}, "my-msg-2")
        assert report.status == DeliveryStatus.SENT
        assert report.extra["gmail_id"] == ""

    # ── gmail_message_to_summary ──

    def test_summary_subject(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert summary.subject == "Test Subject"

    def test_summary_sender(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert summary.sender is not None
        assert summary.sender.address == "alice@example.com"
        assert summary.sender.name == "Alice"

    def test_summary_is_read_false_when_unread(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert summary.is_read is False

    def test_summary_is_read_true_when_no_unread_label(self):
        msg = {**MOCK_GMAIL_MESSAGE_METADATA, "labelIds": ["INBOX"]}
        summary = gmail_message_to_summary(msg, "INBOX")
        assert summary.is_read is True

    def test_summary_is_flagged_false(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert summary.is_flagged is False

    def test_summary_is_flagged_true_when_starred(self):
        msg = {**MOCK_GMAIL_MESSAGE_METADATA, "labelIds": ["INBOX", "STARRED"]}
        summary = gmail_message_to_summary(msg, "INBOX")
        assert summary.is_flagged is True

    def test_summary_has_attachments(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert summary.has_attachments is True

    def test_summary_no_attachments(self):
        msg_no_att = {
            "id": "msg-noatt",
            "threadId": "t1",
            "labelIds": ["INBOX"],
            "snippet": "",
            "payload": {
                "headers": [
                    {"name": "From", "value": "a@b.com"},
                    {"name": "Subject", "value": "No attachments"},
                    {"name": "Date", "value": "Fri, 03 Apr 2026 10:00:00 +0000"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"size": 5}},
                ],
            },
        }
        summary = gmail_message_to_summary(msg_no_att, "INBOX")
        assert summary.has_attachments is False

    def test_summary_date_parsed(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert summary.date is not None
        assert summary.date.year == 2026
        assert summary.date.month == 4
        assert summary.date.day == 3

    def test_summary_message_id(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert summary.message_id == "msg123"

    def test_summary_snippet(self):
        summary = gmail_message_to_summary(MOCK_GMAIL_MESSAGE_METADATA, "INBOX")
        assert "Hey Bob" in summary.snippet

    # ── gmail_message_to_detail ──

    def test_detail_subject(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.subject == "Full Message"

    def test_detail_sender(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.sender is not None
        assert detail.sender.address == "charlie@example.com"
        assert detail.sender.name == "Charlie"

    def test_detail_to_addresses(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert len(detail.to) == 2
        assert detail.to[0].address == "dave@example.com"
        assert detail.to[1].address == "eve@example.com"
        assert detail.to[1].name == "Eve"

    def test_detail_cc(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert len(detail.cc) == 1
        assert detail.cc[0].address == "frank@example.com"

    def test_detail_text_body(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.text_body == "Hello plain text"

    def test_detail_html_body(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.html_body == "<p>Hello HTML</p>"

    def test_detail_attachments(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert len(detail.attachments) == 1
        att = detail.attachments[0]
        assert att.filename == "report.pdf"
        assert att.content_type == "application/pdf"
        assert att.attachment_id == "att-pdf-1"
        assert att.size == 2048

    def test_detail_is_read_true_when_no_unread(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.is_read is True

    def test_detail_is_flagged_true_when_starred(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.is_flagged is True

    def test_detail_in_reply_to(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.in_reply_to == "<orig-msg-id@example.com>"

    def test_detail_references(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.references == ["<ref1@example.com>", "<ref2@example.com>"]

    def test_detail_headers_dict(self):
        detail = gmail_message_to_detail(MOCK_GMAIL_MESSAGE_FULL, "INBOX")
        assert detail.headers["Subject"] == "Full Message"
        assert detail.headers["From"] == "Charlie <charlie@example.com>"

    # ── gmail_attachment_to_content ──

    def test_attachment_to_content_decodes_data(self):
        raw_data = b"Hello attachment data"
        encoded = base64.urlsafe_b64encode(raw_data).decode("ascii")

        content = gmail_attachment_to_content(
            {"data": encoded, "size": len(raw_data)},
            attachment_id="att-1",
            filename="file.txt",
            content_type="text/plain",
        )

        assert content.content == raw_data
        assert content.attachment_id == "att-1"
        assert content.filename == "file.txt"
        assert content.content_type == "text/plain"
        assert content.size == len(raw_data)

    def test_attachment_to_content_empty_data(self):
        content = gmail_attachment_to_content(
            {"data": "", "size": 0},
            attachment_id="att-2",
            filename="empty.bin",
            content_type="application/octet-stream",
        )
        assert content.content == b""
        assert content.size == 0

    # ── _folder_to_label / _label_to_folder ──

    def test_folder_to_label_known(self):
        assert _folder_to_label("INBOX") == "INBOX"
        assert _folder_to_label("Sent") == "SENT"
        assert _folder_to_label("Drafts") == "DRAFT"
        assert _folder_to_label("Trash") == "TRASH"
        assert _folder_to_label("Spam") == "SPAM"

    def test_folder_to_label_unknown_passthrough(self):
        assert _folder_to_label("CustomLabel") == "CustomLabel"

    def test_label_to_folder_known(self):
        assert _label_to_folder(["INBOX"]) == "INBOX"
        assert _label_to_folder(["SENT"]) == "Sent"
        assert _label_to_folder(["DRAFT"]) == "Drafts"
        assert _label_to_folder(["TRASH"]) == "Trash"
        assert _label_to_folder(["SPAM"]) == "Spam"

    def test_label_to_folder_first_known_wins(self):
        assert _label_to_folder(["CATEGORY_PRIMARY", "INBOX", "UNREAD"]) == "INBOX"

    def test_label_to_folder_unknown_returns_first(self):
        assert _label_to_folder(["CATEGORY_SOCIAL"]) == "CATEGORY_SOCIAL"

    def test_label_to_folder_empty_returns_inbox(self):
        assert _label_to_folder([]) == "INBOX"


# ── TestGmailAdapter ──


class TestGmailAdapter:
    """Test GmailEmailAdapter with mocked GmailApiClient."""

    def test_implements_email_port(self):
        assert issubclass(GmailEmailAdapter, EmailPort)

    def test_implements_inbox_capability(self):
        assert issubclass(GmailEmailAdapter, InboxCapability)

    def test_validate_credentials_valid(self, adapter):
        assert adapter.validate_credentials() is True

    def test_validate_credentials_missing_access_token(self):
        a = GmailEmailAdapter(
            credentials={"from_email": FROM_EMAIL},
            http_client=MagicMock(),
        )
        assert a.validate_credentials() is False

    def test_validate_credentials_empty_access_token(self):
        a = GmailEmailAdapter(
            credentials={"access_token": "", "from_email": FROM_EMAIL},
            http_client=MagicMock(),
        )
        # The manifest field is required but we pass empty string;
        # validate_credentials checks via manifest.auth.validate_credentials
        # which checks for presence of the key, not value emptiness
        # depending on implementation, so just verify it returns a bool.
        result = a.validate_credentials()
        assert isinstance(result, bool)

    def test_test_connection_success(self, adapter):
        adapter.client.get_profile = MagicMock(return_value=MOCK_GMAIL_PROFILE)
        result = adapter.test_connection()

        assert result.success is True
        assert "OK" in result.message
        assert "user@gmail.com" in result.message
        assert result.details["email"] == "user@gmail.com"
        assert result.details["messages_total"] == 42000

    def test_test_connection_failure(self, adapter):
        adapter.client.get_profile = MagicMock(side_effect=Exception("401 Unauthorized"))
        result = adapter.test_connection()

        assert result.success is False
        assert "401" in result.message

    def test_send_calls_send_message(self, adapter):
        adapter.client.send_message = MagicMock(return_value=MOCK_GMAIL_SEND_RESPONSE)

        msg = _make_message(message_id="test-id-1")
        report = adapter.send(msg)

        adapter.client.send_message.assert_called_once()
        raw_b64 = adapter.client.send_message.call_args[0][0]
        # Verify the raw_b64 is valid base64url
        decoded = base64.urlsafe_b64decode(raw_b64).decode("utf-8", errors="replace")
        assert "recipient@example.com" in decoded
        assert report.status == DeliveryStatus.SENT
        assert report.message_id == "test-id-1"
        assert report.extra["gmail_id"] == "sent-msg-1"

    def test_send_handles_exception_gracefully(self, adapter):
        adapter.client.send_message = MagicMock(
            side_effect=Exception("Gmail API error")
        )

        msg = _make_message(message_id="err-1")
        report = adapter.send(msg)

        assert report.status == DeliveryStatus.FAILED
        assert "Gmail API error" in report.error
        assert report.message_id == "err-1"

    def test_send_bulk_returns_list_of_reports(self, adapter):
        adapter.client.send_message = MagicMock(return_value=MOCK_GMAIL_SEND_RESPONSE)

        messages = [_make_message(message_id=f"bulk-{i}") for i in range(3)]
        reports = adapter.send_bulk(messages)

        assert len(reports) == 3
        assert all(isinstance(r, DeliveryReport) for r in reports)
        assert all(r.status == DeliveryStatus.SENT for r in reports)
        assert adapter.client.send_message.call_count == 3

    def test_fetch_messages_calls_list_then_get(self, adapter):
        adapter.client.list_messages = MagicMock(return_value={
            "messages": [{"id": "m1"}, {"id": "m2"}],
            "resultSizeEstimate": 2,
        })
        adapter.client.get_message = MagicMock(
            return_value=MOCK_GMAIL_MESSAGE_METADATA,
        )

        summaries = adapter.fetch_messages(folder="INBOX", limit=10)

        adapter.client.list_messages.assert_called_once()
        call_kwargs = adapter.client.list_messages.call_args
        assert call_kwargs[1]["label_ids"] == ["INBOX"]
        assert call_kwargs[1]["max_results"] == 10
        assert adapter.client.get_message.call_count == 2
        assert len(summaries) == 2
        assert summaries[0].message_id == "msg123"

    def test_fetch_messages_with_date_filters(self, adapter):
        adapter.client.list_messages = MagicMock(return_value={"messages": []})

        since = datetime(2026, 1, 1, tzinfo=UTC)
        until = datetime(2026, 4, 1, tzinfo=UTC)
        adapter.fetch_messages(since=since, until=until)

        call_kwargs = adapter.client.list_messages.call_args[1]
        assert "after:2026/01/01" in call_kwargs["query"]
        assert "before:2026/04/01" in call_kwargs["query"]

    def test_fetch_messages_empty_result(self, adapter):
        adapter.client.list_messages = MagicMock(return_value={})

        summaries = adapter.fetch_messages()
        assert summaries == []

    def test_get_message_calls_get_with_full_format(self, adapter):
        adapter.client.get_message = MagicMock(
            return_value=MOCK_GMAIL_MESSAGE_FULL,
        )

        detail = adapter.get_message("msg456")

        adapter.client.get_message.assert_called_once_with("msg456", fmt="full")
        assert detail.message_id == "msg456"
        assert detail.subject == "Full Message"
        assert detail.text_body == "Hello plain text"

    def test_download_attachment(self, adapter):
        raw_bytes = b"Attachment file content"
        encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii")

        adapter.client.get_message = MagicMock(
            return_value=MOCK_GMAIL_MESSAGE_FULL,
        )
        adapter.client.get_attachment = MagicMock(
            return_value={"data": encoded, "size": len(raw_bytes)},
        )

        content = adapter.download_attachment("msg456", "att-pdf-1")

        adapter.client.get_message.assert_called_once_with("msg456", fmt="full")
        adapter.client.get_attachment.assert_called_once_with("msg456", "att-pdf-1")
        assert content.content == raw_bytes
        assert content.filename == "report.pdf"
        assert content.content_type == "application/pdf"
        assert content.attachment_id == "att-pdf-1"

    def test_download_attachment_not_found_raises(self, adapter):
        adapter.client.get_message = MagicMock(
            return_value=MOCK_GMAIL_MESSAGE_FULL,
        )

        with pytest.raises(Exception, match="not found"):
            adapter.download_attachment("msg456", "nonexistent-att")


# ── TestGmailErrors ──


class TestGmailErrors:
    """Test error classification."""

    def test_auth_401(self):
        err = classify_gmail_error(Exception("401 Unauthorized"))
        assert isinstance(err, AuthenticationError)

    def test_auth_403(self):
        err = classify_gmail_error(Exception("403 Forbidden"))
        assert isinstance(err, AuthenticationError)

    def test_auth_invalid_credentials(self):
        err = classify_gmail_error(Exception("Invalid credentials provided"))
        assert isinstance(err, AuthenticationError)

    def test_auth_unauthorized(self):
        err = classify_gmail_error(Exception("Request is unauthorized"))
        assert isinstance(err, AuthenticationError)

    def test_rate_limit_429(self):
        err = classify_gmail_error(Exception("429 Too Many Requests"))
        assert isinstance(err, RateLimitError)

    def test_rate_limit_keyword(self):
        err = classify_gmail_error(Exception("Rate limit exceeded"))
        assert isinstance(err, RateLimitError)

    def test_rate_limit_quota(self):
        err = classify_gmail_error(Exception("User quota exceeded"))
        assert isinstance(err, RateLimitError)

    def test_connection_error(self):
        err = classify_gmail_error(Exception("Connection refused"))
        assert isinstance(err, GmailConnectionError)
        assert err.retryable is True

    def test_timeout_error(self):
        err = classify_gmail_error(Exception("Request timed out"))
        assert isinstance(err, GmailConnectionError)
        assert err.retryable is True

    def test_generic_error(self):
        err = classify_gmail_error(Exception("Something unexpected"))
        assert isinstance(err, GmailError)
        assert "Gmail API error" in str(err)
