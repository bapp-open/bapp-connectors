"""
SMTP integration tests — runs against MailHog in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d
    uv run --extra dev pytest tests/messaging/smtp/ -v -m integration

MailHog captures all emails sent to port 1025 and exposes them via
its HTTP API on port 8025 for verification.
"""

from __future__ import annotations

import json
import uuid
from urllib.request import Request, urlopen

import pytest

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    MessageChannel,
    OutboundMessage,
)
from bapp_connectors.providers.messaging.smtp.adapter import SMTPMessagingAdapter
from tests.messaging.conftest import (
    MAILHOG_API_PORT,
    MAILHOG_HOST,
    MAILHOG_SMTP_PORT,
    skip_unless_mailhog,
)

pytestmark = [pytest.mark.integration, skip_unless_mailhog]

MAILHOG_API = f"http://{MAILHOG_HOST}:{MAILHOG_API_PORT}"
FROM_EMAIL = "test@bapp.local"
TO_EMAIL = "recipient@bapp.local"


def _mailhog_get_messages() -> list[dict]:
    """Fetch all messages from MailHog API."""
    req = Request(f"{MAILHOG_API}/api/v2/messages")
    with urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    return data.get("items", [])


def _mailhog_delete_messages():
    """Clear all messages in MailHog."""
    req = Request(f"{MAILHOG_API}/api/v1/messages", method="DELETE")
    try:
        urlopen(req, timeout=5)
    except Exception:
        pass


@pytest.fixture
def adapter():
    return SMTPMessagingAdapter(
        credentials={
            "host": MAILHOG_HOST,
            "port": str(MAILHOG_SMTP_PORT),
            "username": "",
            "password": "",
            "from_email": FROM_EMAIL,
            "use_tls": "false",
            "use_ssl": "false",
        },
    )


@pytest.fixture(autouse=True)
def clean_mailbox():
    """Clear MailHog before each test."""
    _mailhog_delete_messages()
    yield
    _mailhog_delete_messages()


@pytest.fixture
def test_recipient():
    return TO_EMAIL


# ── Contract Tests ──


class TestSMTPContract:
    from tests.messaging.contract import MessagingContractTests

    for _name, _method in vars(MessagingContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Connection ──


class TestSMTPConnection:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True


# ── Sending ──


class TestSMTPSending:

    def test_send_plain_text_email(self, adapter):
        tag = uuid.uuid4().hex[:8]
        message = OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=TO_EMAIL,
            subject=f"Plain Test {tag}",
            body="Hello from SMTP integration test.",
        )
        report = adapter.send(message)
        assert report.status == DeliveryStatus.SENT

        # Verify via MailHog API
        messages = _mailhog_get_messages()
        assert any(tag in m["Content"]["Headers"]["Subject"][0] for m in messages)

    def test_send_html_email(self, adapter):
        tag = uuid.uuid4().hex[:8]
        message = OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=TO_EMAIL,
            subject=f"HTML Test {tag}",
            body="Fallback plain text",
            html_body="<h1>Hello</h1><p>HTML email test.</p>",
        )
        report = adapter.send(message)
        assert report.status == DeliveryStatus.SENT

        messages = _mailhog_get_messages()
        matching = [m for m in messages if tag in m["Content"]["Headers"]["Subject"][0]]
        assert len(matching) == 1

    def test_send_bulk(self, adapter):
        tag = uuid.uuid4().hex[:8]
        messages = [
            OutboundMessage(
                channel=MessageChannel.EMAIL,
                to=TO_EMAIL,
                subject=f"Bulk {tag} #{i}",
                body=f"Bulk message {i}.",
            )
            for i in range(3)
        ]
        reports = adapter.send_bulk(messages)
        assert len(reports) == 3
        assert all(r.status == DeliveryStatus.SENT for r in reports)

        # Verify all 3 arrived
        received = _mailhog_get_messages()
        matching = [m for m in received if tag in m["Content"]["Headers"]["Subject"][0]]
        assert len(matching) == 3

    def test_send_with_cc(self, adapter):
        tag = uuid.uuid4().hex[:8]
        message = OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=TO_EMAIL,
            subject=f"CC Test {tag}",
            body="Message with CC.",
            extra={"cc": ["cc@bapp.local"]},
        )
        report = adapter.send(message)
        assert report.status == DeliveryStatus.SENT

    def test_send_with_attachment(self, adapter):
        tag = uuid.uuid4().hex[:8]
        message = OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=TO_EMAIL,
            subject=f"Attachment Test {tag}",
            body="See attached.",
            attachments=[{
                "filename": "test.txt",
                "content": b"Hello attachment!",
                "content_type": "text/plain",
            }],
        )
        report = adapter.send(message)
        assert report.status == DeliveryStatus.SENT

        messages = _mailhog_get_messages()
        matching = [m for m in messages if tag in m["Content"]["Headers"]["Subject"][0]]
        assert len(matching) == 1


# ── Delivery Verification ──


class TestSMTPDeliveryVerification:

    def test_email_arrives_with_correct_sender(self, adapter):
        adapter.send(OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=TO_EMAIL,
            subject="Sender Test",
            body="Check sender.",
        ))
        messages = _mailhog_get_messages()
        assert len(messages) >= 1
        from_header = messages[0]["Content"]["Headers"].get("From", [""])[0]
        assert FROM_EMAIL in from_header

    def test_email_arrives_with_correct_recipient(self, adapter):
        adapter.send(OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=TO_EMAIL,
            subject="Recipient Test",
            body="Check recipient.",
        ))
        messages = _mailhog_get_messages()
        assert len(messages) >= 1
        to_header = messages[0]["Content"]["Headers"].get("To", [""])[0]
        assert TO_EMAIL in to_header
