"""
SMTP + IMAP email integration tests — runs against real mail server.

Requires EMAIL_TEST_* env vars (see .env).

    set -a && source .env && set +a
    uv run --extra dev pytest tests/messaging/smtp/test_email_integration.py -v -m integration
"""

from __future__ import annotations

import time
import uuid

import pytest

from bapp_connectors.core.dto import (
    DeliveryStatus,
    EmailDetail,
    EmailSummary,
    MessageChannel,
    OutboundMessage,
)
from bapp_connectors.providers.messaging.smtp.adapter import SMTPMessagingAdapter
from tests.messaging.conftest import (
    EMAIL_TEST_IMAP_HOST,
    EMAIL_TEST_IMAP_PORT,
    EMAIL_TEST_PASSWORD,
    EMAIL_TEST_RECIPIENT,
    EMAIL_TEST_SMTP_HOST,
    EMAIL_TEST_SMTP_PORT,
    EMAIL_TEST_USER,
    skip_unless_email,
)

pytestmark = [pytest.mark.integration, skip_unless_email]


@pytest.fixture
def adapter():
    return SMTPMessagingAdapter(
        credentials={
            "host": EMAIL_TEST_SMTP_HOST,
            "port": str(EMAIL_TEST_SMTP_PORT),
            "username": EMAIL_TEST_USER,
            "password": EMAIL_TEST_PASSWORD,
            "from_email": EMAIL_TEST_USER,
            "use_tls": "true",
            "use_ssl": "false",
            "imap_host": EMAIL_TEST_IMAP_HOST,
            "imap_port": str(EMAIL_TEST_IMAP_PORT),
            "imap_use_ssl": "true",
        },
    )


# ── Connection ──


class TestEmailConnection:

    def test_smtp_and_imap_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert "SMTP: OK" in result.message
        assert "IMAP: OK" in result.message


# ── IMAP Inbox Reading ──


class TestIMAPInboxReading:

    def test_fetch_messages_returns_summaries(self, adapter):
        """Fetch recent messages from INBOX — should find at least the test email from pidginhost."""
        messages = adapter.fetch_messages(folder="INBOX", limit=10)
        assert len(messages) > 0
        assert all(isinstance(m, EmailSummary) for m in messages)
        print(f"\n  Found {len(messages)} messages in INBOX:")
        for m in messages:
            sender = m.sender.address if m.sender else "?"
            print(f"    [{m.message_id}] {m.subject} — from {sender} — attachments={m.has_attachments}")

    def test_find_test_email_from_pidginhost(self, adapter):
        """The email from cristi@pidginhost.com with subject 'Test message' should be in INBOX."""
        messages = adapter.fetch_messages(folder="INBOX", limit=50)
        matching = [
            m for m in messages
            if m.sender and m.sender.address == "cristi@pidginhost.com"
        ]
        assert len(matching) > 0, "Expected to find email from cristi@pidginhost.com"
        msg = matching[0]
        print(f"\n  Found: [{msg.message_id}] '{msg.subject}' from {msg.sender.address}")
        assert msg.has_attachments is True

    def test_get_message_full_detail(self, adapter):
        """Fetch full detail of the pidginhost test email."""
        messages = adapter.fetch_messages(folder="INBOX", limit=50)
        matching = [
            m for m in messages
            if m.sender and m.sender.address == "cristi@pidginhost.com"
        ]
        assert len(matching) > 0, "Expected to find email from cristi@pidginhost.com"

        detail = adapter.get_message(matching[0].message_id, folder="INBOX")
        assert isinstance(detail, EmailDetail)
        print(f"\n  Subject: {detail.subject}")
        print(f"  From: {detail.sender.address if detail.sender else '?'}")
        print(f"  To: {[a.address for a in detail.to]}")
        print(f"  Text body: {detail.text_body[:200]!r}")
        print(f"  HTML body: {detail.html_body[:200]!r}")
        print(f"  Attachments: {len(detail.attachments)}")
        for att in detail.attachments:
            print(f"    - {att.filename} ({att.content_type}, {att.size} bytes)")

    def test_download_attachment(self, adapter):
        """Download the attachment from the pidginhost test email."""
        messages = adapter.fetch_messages(folder="INBOX", limit=50)
        matching = [
            m for m in messages
            if m.sender and m.sender.address == "cristi@pidginhost.com" and m.has_attachments
        ]
        assert len(matching) > 0, "Expected to find email with attachment from pidginhost"

        detail = adapter.get_message(matching[0].message_id, folder="INBOX")
        assert len(detail.attachments) > 0, "Expected at least one attachment"

        att_info = detail.attachments[0]
        content = adapter.download_attachment(
            matching[0].message_id, att_info.attachment_id, folder="INBOX",
        )
        assert content.content is not None
        assert len(content.content) > 0
        print(f"\n  Downloaded: {content.filename} ({content.content_type}, {content.size} bytes)")


# ── SMTP Sending + IMAP Verification ──


class TestSendAndVerifyViaIMAP:

    def test_send_email_and_find_in_inbox(self, adapter):
        """Send an email to the recipient and verify it arrives via IMAP.

        Since office@cbsoft.ro forwards to cristi@cbsoft.ro, we check
        the sender's own INBOX for the forwarded copy.
        """
        tag = uuid.uuid4().hex[:8]
        subject = f"bapp-connectors integration test {tag}"

        # Send
        report = adapter.send(OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=EMAIL_TEST_RECIPIENT,
            subject=subject,
            body=f"Integration test {tag} — plain text.",
            html_body=f"<p>Integration test <code>{tag}</code></p>",
        ))
        assert report.status == DeliveryStatus.SENT
        print(f"\n  Sent email with subject: {subject}")

        # Wait for delivery + forwarding
        found = False
        for attempt in range(6):
            time.sleep(5)
            messages = adapter.fetch_messages(folder="INBOX", limit=20)
            matching = [m for m in messages if tag in m.subject]
            if matching:
                found = True
                detail = adapter.get_message(matching[0].message_id, folder="INBOX")
                print(f"  Found after {(attempt + 1) * 5}s: '{detail.subject}'")
                print(f"  Body: {detail.text_body[:200]!r}")
                assert tag in detail.text_body or tag in detail.html_body
                break

        assert found, f"Email with tag {tag} not found in INBOX after 30s"
