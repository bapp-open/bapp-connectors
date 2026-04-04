"""
Mailchimp Transactional (Mandrill) unit tests — no network.

Tests: manifest, mappers (outbound + result), adapter (send, send_bulk,
template routing, credential validation, connection test, error handling).
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    MessageChannel,
    OutboundMessage,
)
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.core.types import ProviderFamily
from bapp_connectors.providers.email.mailchimp.adapter import MailchimpEmailAdapter
from bapp_connectors.providers.email.mailchimp.errors import (
    MandrillAPIError,
    MandrillConnectionError,
    classify_mandrill_error,
)
from bapp_connectors.providers.email.mailchimp.manifest import manifest
from bapp_connectors.providers.email.mailchimp.mappers import (
    mandrill_result_to_report,
    outbound_to_mandrill,
)

API_KEY = "test-mandrill-key"
FROM_EMAIL = "sender@example.com"
FROM_NAME = "Test Sender"


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
    """Create a MailchimpEmailAdapter with a mocked HTTP client."""
    mock_http = MagicMock()
    return MailchimpEmailAdapter(
        credentials={
            "api_key": API_KEY,
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
        },
        http_client=mock_http,
    )


# ── TestMailchimpManifest ──


class TestMailchimpManifest:
    def test_name(self):
        assert manifest.name == "mailchimp"

    def test_family(self):
        assert manifest.family == ProviderFamily.EMAIL

    def test_capabilities(self):
        assert EmailPort in manifest.capabilities

    def test_display_name(self):
        assert manifest.display_name == "Mailchimp Transactional"


# ── TestMailchimpMappers ──


class TestMailchimpMappers:
    """Test outbound_to_mandrill and mandrill_result_to_report."""

    # ── outbound_to_mandrill ──

    def test_basic_fields(self):
        msg = _make_message(html_body="<p>Hello</p>")
        result = outbound_to_mandrill(msg, default_from_email=FROM_EMAIL)

        assert result["from_email"] == FROM_EMAIL
        assert result["subject"] == "Test Subject"
        assert result["text"] == "Plain text body."
        assert result["html"] == "<p>Hello</p>"
        assert result["to"] == [{"email": "recipient@example.com", "type": "to"}]

    def test_cc_bcc(self):
        msg = _make_message(extra={
            "cc": ["cc1@example.com", "cc2@example.com"],
            "bcc": ["bcc@example.com"],
        })
        result = outbound_to_mandrill(msg, default_from_email=FROM_EMAIL)

        recipients = result["to"]
        assert len(recipients) == 4
        assert recipients[0] == {"email": "recipient@example.com", "type": "to"}
        assert recipients[1] == {"email": "cc1@example.com", "type": "cc"}
        assert recipients[2] == {"email": "cc2@example.com", "type": "cc"}
        assert recipients[3] == {"email": "bcc@example.com", "type": "bcc"}

    def test_attachments_base64(self):
        content = b"file content bytes"
        msg = _make_message(attachments=[
            {
                "filename": "report.pdf",
                "content": content,
                "content_type": "application/pdf",
            },
        ])
        result = outbound_to_mandrill(msg, default_from_email=FROM_EMAIL)

        assert "attachments" in result
        att = result["attachments"][0]
        assert att["name"] == "report.pdf"
        assert att["type"] == "application/pdf"
        assert att["content"] == base64.b64encode(content).decode("ascii")

    def test_attachments_already_base64_string(self):
        """If attachment content is already a string, it is passed through."""
        msg = _make_message(attachments=[
            {
                "filename": "file.txt",
                "content": "dGVzdA==",
                "content_type": "text/plain",
            },
        ])
        result = outbound_to_mandrill(msg, default_from_email=FROM_EMAIL)
        assert result["attachments"][0]["content"] == "dGVzdA=="

    def test_from_override_via_extra(self):
        msg = _make_message(extra={
            "from_email": "override@example.com",
            "from_name": "Override Name",
        })
        result = outbound_to_mandrill(
            msg,
            default_from_email=FROM_EMAIL,
            default_from_name=FROM_NAME,
        )
        assert result["from_email"] == "override@example.com"
        assert result["from_name"] == "Override Name"

    def test_default_from_name(self):
        msg = _make_message()
        result = outbound_to_mandrill(
            msg,
            default_from_email=FROM_EMAIL,
            default_from_name=FROM_NAME,
        )
        assert result["from_name"] == FROM_NAME

    def test_template_merge_vars(self):
        msg = _make_message(template_vars={"FNAME": "Alice", "ORDER_ID": "1234"})
        result = outbound_to_mandrill(msg, default_from_email=FROM_EMAIL)

        merge_vars = result["global_merge_vars"]
        names = {v["name"] for v in merge_vars}
        assert "FNAME" in names
        assert "ORDER_ID" in names

    def test_reply_to_header(self):
        msg = _make_message(extra={"reply_to": "reply@example.com"})
        result = outbound_to_mandrill(msg, default_from_email=FROM_EMAIL)
        assert result["headers"]["Reply-To"] == "reply@example.com"

    def test_tags_and_metadata(self):
        msg = _make_message(extra={
            "tags": ["welcome", "onboarding"],
            "metadata": {"user_id": "42"},
        })
        result = outbound_to_mandrill(msg, default_from_email=FROM_EMAIL)
        assert result["tags"] == ["welcome", "onboarding"]
        assert result["metadata"] == {"user_id": "42"}

    # ── mandrill_result_to_report ──

    def test_result_sent(self):
        result = [{"email": "r@ex.com", "status": "sent", "_id": "abc123"}]
        report = mandrill_result_to_report(result, "msg-1")

        assert report.status == DeliveryStatus.SENT
        assert report.message_id == "msg-1"
        assert report.error == ""
        assert report.extra["mandrill_id"] == "abc123"

    def test_result_queued(self):
        result = [{"email": "r@ex.com", "status": "queued", "_id": "def456"}]
        report = mandrill_result_to_report(result, "msg-2")
        assert report.status == DeliveryStatus.QUEUED

    def test_result_rejected(self):
        result = [{"email": "r@ex.com", "status": "rejected", "reject_reason": "hard-bounce", "_id": "ghi"}]
        report = mandrill_result_to_report(result, "msg-3")

        assert report.status == DeliveryStatus.REJECTED
        assert "hard-bounce" in report.error

    def test_result_invalid(self):
        result = [{"email": "r@ex.com", "status": "invalid", "_id": "jkl"}]
        report = mandrill_result_to_report(result, "msg-4")
        assert report.status == DeliveryStatus.FAILED

    def test_result_empty(self):
        report = mandrill_result_to_report([], "msg-5")
        assert report.status == DeliveryStatus.FAILED
        assert "Empty response" in report.error


# ── TestMailchimpAdapter ──


class TestMailchimpAdapter:
    """Test MailchimpEmailAdapter with mocked MandrillApiClient."""

    def test_validate_credentials_valid(self, adapter):
        assert adapter.validate_credentials() is True

    def test_validate_credentials_missing_key(self):
        a = MailchimpEmailAdapter(
            credentials={"from_email": FROM_EMAIL},
            http_client=MagicMock(),
        )
        assert a.validate_credentials() is False

    def test_test_connection_success(self, adapter):
        adapter.client.test_auth = MagicMock(return_value=True)
        result = adapter.test_connection()
        assert result.success is True
        assert "OK" in result.message

    def test_test_connection_failure(self, adapter):
        adapter.client.test_auth = MagicMock(return_value=False)
        result = adapter.test_connection()
        assert result.success is False

    def test_test_connection_exception(self, adapter):
        adapter.client.test_auth = MagicMock(side_effect=Exception("timeout"))
        result = adapter.test_connection()
        assert result.success is False
        assert "timeout" in result.message

    def test_send_calls_send_message(self, adapter):
        mandrill_response = [{"email": "r@ex.com", "status": "sent", "_id": "m1"}]
        adapter.client.send_message = MagicMock(return_value=mandrill_response)

        msg = _make_message(message_id="test-id-1")
        report = adapter.send(msg)

        adapter.client.send_message.assert_called_once()
        payload = adapter.client.send_message.call_args[0][0]
        assert payload["to"][0]["email"] == "recipient@example.com"
        assert payload["subject"] == "Test Subject"
        assert report.status == DeliveryStatus.SENT
        assert report.message_id == "test-id-1"

    def test_send_with_template_routes_to_send_template(self, adapter):
        mandrill_response = [{"email": "r@ex.com", "status": "queued", "_id": "m2"}]
        adapter.client.send_template = MagicMock(return_value=mandrill_response)

        msg = _make_message(
            message_id="tmpl-1",
            template_id="welcome-email",
            template_vars={"FNAME": "Alice"},
        )
        report = adapter.send(msg)

        adapter.client.send_template.assert_called_once()
        call_kwargs = adapter.client.send_template.call_args
        assert call_kwargs[1]["template_name"] == "welcome-email"
        assert report.status == DeliveryStatus.QUEUED

    def test_send_bulk_returns_list_of_reports(self, adapter):
        mandrill_response = [{"email": "r@ex.com", "status": "sent", "_id": "b1"}]
        adapter.client.send_message = MagicMock(return_value=mandrill_response)

        messages = [_make_message(message_id=f"bulk-{i}") for i in range(3)]
        reports = adapter.send_bulk(messages)

        assert len(reports) == 3
        assert all(isinstance(r, DeliveryReport) for r in reports)
        assert all(r.status == DeliveryStatus.SENT for r in reports)
        assert adapter.client.send_message.call_count == 3

    def test_send_handles_exception_gracefully(self, adapter):
        adapter.client.send_message = MagicMock(side_effect=Exception("API error"))

        msg = _make_message(message_id="err-1")
        report = adapter.send(msg)

        assert report.status == DeliveryStatus.FAILED
        assert "API error" in report.error
        assert report.message_id == "err-1"


# ── TestMailchimpErrors ──


class TestMailchimpErrors:
    """Test error classification."""

    def test_invalid_key(self):
        err = classify_mandrill_error(Exception("Invalid_Key: bad key"))
        assert "authentication" in str(err).lower()

    def test_connection_error(self):
        err = classify_mandrill_error(Exception("Connection timed out"))
        assert isinstance(err, MandrillConnectionError)
        assert err.retryable is True

    def test_generic_api_error(self):
        err = classify_mandrill_error(Exception("Unknown error happened"))
        assert isinstance(err, MandrillAPIError)
