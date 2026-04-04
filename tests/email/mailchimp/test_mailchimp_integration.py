"""
Mailchimp Transactional (Mandrill) integration tests — runs against real API.

Requires MAILCHIMP_API_KEY env var (see .env).

    set -a && source .env && set +a
    uv run --extra dev pytest tests/email/mailchimp/test_mailchimp_integration.py -v -m integration -s
"""

from __future__ import annotations

import os
import uuid

import pytest

from bapp_connectors.core.dto import (
    DeliveryStatus,
    MessageChannel,
    OutboundMessage,
)
from bapp_connectors.providers.email.mailchimp.adapter import MailchimpEmailAdapter

MAILCHIMP_API_KEY = os.environ.get("MAILCHIMP_API_KEY", "")
MAILCHIMP_FROM_EMAIL = os.environ.get("MAILCHIMP_FROM_EMAIL", "")
MAILCHIMP_TO_EMAIL = os.environ.get("MAILCHIMP_TO_EMAIL", "")

skip_unless_mailchimp = pytest.mark.skipif(
    not MAILCHIMP_API_KEY or not MAILCHIMP_FROM_EMAIL or not MAILCHIMP_TO_EMAIL,
    reason="MAILCHIMP_* env vars not set. Export them or source .env",
)

pytestmark = [pytest.mark.integration, skip_unless_mailchimp]


@pytest.fixture
def adapter():
    return MailchimpEmailAdapter(
        credentials={
            "api_key": MAILCHIMP_API_KEY,
            "from_email": MAILCHIMP_FROM_EMAIL,
            "from_name": "BAPP Connectors Test",
        },
    )


# ── Connection ──


class TestMailchimpConnection:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        print(f"\n  Connection: {result.message}")


# ── Sending ──


class TestMailchimpSending:

    def test_send_plain_text(self, adapter):
        tag = uuid.uuid4().hex[:8]
        message = OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=MAILCHIMP_TO_EMAIL,
            subject=f"Mailchimp Integration Test {tag}",
            body=f"Plain text test via Mandrill API. Tag: {tag}",
        )
        report = adapter.send(message)
        print(f"\n  Send result: {report.status} (id={report.message_id})")
        print(f"  Extra: {report.extra}")
        assert report.status in (DeliveryStatus.SENT, DeliveryStatus.QUEUED)

    def test_send_html(self, adapter):
        tag = uuid.uuid4().hex[:8]
        message = OutboundMessage(
            channel=MessageChannel.EMAIL,
            to=MAILCHIMP_TO_EMAIL,
            subject=f"Mailchimp HTML Test {tag}",
            body="Fallback plain text",
            html_body=f"<h2>Mailchimp Test</h2><p>Tag: <code>{tag}</code></p>",
        )
        report = adapter.send(message)
        assert report.status in (DeliveryStatus.SENT, DeliveryStatus.QUEUED)

    def test_send_bulk(self, adapter):
        tag = uuid.uuid4().hex[:8]
        messages = [
            OutboundMessage(
                channel=MessageChannel.EMAIL,
                to=MAILCHIMP_TO_EMAIL,
                subject=f"Mailchimp Bulk {tag} #{i}",
                body=f"Bulk message {i}.",
            )
            for i in range(2)
        ]
        reports = adapter.send_bulk(messages)
        assert len(reports) == 2
        assert all(r.status in (DeliveryStatus.SENT, DeliveryStatus.QUEUED) for r in reports)
