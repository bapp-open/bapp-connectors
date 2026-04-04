"""
Amazon SES unit tests — no network, no real AWS credentials.

Tests: manifest, mappers (outbound kwargs, raw MIME, response), adapter
(send simple/raw, send_bulk, credential validation, connection test, errors).
"""

from __future__ import annotations

import email
from email import policy as email_policy
from unittest.mock import MagicMock, patch

import pytest

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    MessageChannel,
    OutboundMessage,
)
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.core.types import ProviderFamily
from bapp_connectors.providers.email.ses.errors import (
    SESConnectionError,
    SESError,
    classify_ses_error,
)
from bapp_connectors.providers.email.ses.manifest import manifest
from bapp_connectors.providers.email.ses.mappers import (
    outbound_to_raw_mime,
    outbound_to_ses_kwargs,
    ses_response_to_report,
)

FROM_EMAIL = "sender@example.com"
ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _make_message(**overrides) -> OutboundMessage:
    """Build a minimal OutboundMessage with sensible defaults."""
    defaults = {
        "channel": MessageChannel.EMAIL,
        "to": "recipient@example.com",
        "subject": "Test Subject",
        "body": "Plain text body.",
        "extra": {},
    }
    defaults.update(overrides)
    return OutboundMessage(**defaults)


@pytest.fixture
def mock_boto3_session():
    """Patch boto3.session.Session so SESClient never touches AWS."""
    with patch("bapp_connectors.providers.email.ses.client.boto3") as mock_boto3:
        mock_session = MagicMock()
        mock_ses_client = MagicMock()
        mock_session.client.return_value = mock_ses_client
        mock_boto3.session.Session.return_value = mock_session
        # Ensure boto3 is not None so _require_boto3 passes
        mock_boto3.__bool__ = lambda self: True
        yield mock_ses_client


@pytest.fixture
def adapter(mock_boto3_session):
    """Create an SESEmailAdapter with mocked boto3."""
    from bapp_connectors.providers.email.ses.adapter import SESEmailAdapter

    a = SESEmailAdapter(
        credentials={
            "access_key_id": ACCESS_KEY,
            "secret_access_key": SECRET_KEY,
            "from_email": FROM_EMAIL,
        },
        config={"region": "eu-west-1"},
    )
    # Replace the inner ses client with the mock
    a.client.ses = mock_boto3_session
    return a


# ── TestSESManifest ──


class TestSESManifest:
    def test_name(self):
        assert manifest.name == "ses"

    def test_family(self):
        assert manifest.family == ProviderFamily.EMAIL

    def test_capabilities(self):
        assert EmailPort in manifest.capabilities

    def test_display_name(self):
        assert manifest.display_name == "Amazon SES"

    def test_settings_region(self):
        field_names = [f.name for f in manifest.settings.fields]
        assert "region" in field_names

    def test_settings_configuration_set(self):
        field_names = [f.name for f in manifest.settings.fields]
        assert "configuration_set" in field_names


# ── TestSESMappers ──


class TestSESMappers:
    """Test outbound_to_ses_kwargs, outbound_to_raw_mime, ses_response_to_report."""

    # ── outbound_to_ses_kwargs ──

    def test_basic_email(self):
        msg = _make_message(html_body="<p>Hi</p>")
        kwargs = outbound_to_ses_kwargs(msg, default_from_email=FROM_EMAIL)

        assert kwargs["from_email"] == FROM_EMAIL
        assert kwargs["to"] == ["recipient@example.com"]
        assert kwargs["subject"] == "Test Subject"
        assert kwargs["body_text"] == "Plain text body."
        assert kwargs["body_html"] == "<p>Hi</p>"

    def test_cc_bcc(self):
        msg = _make_message(extra={
            "cc": ["cc@example.com"],
            "bcc": ["bcc@example.com"],
        })
        kwargs = outbound_to_ses_kwargs(msg, default_from_email=FROM_EMAIL)

        assert kwargs["cc"] == ["cc@example.com"]
        assert kwargs["bcc"] == ["bcc@example.com"]

    def test_cc_as_string_wrapped_in_list(self):
        msg = _make_message(extra={"cc": "single@example.com"})
        kwargs = outbound_to_ses_kwargs(msg, default_from_email=FROM_EMAIL)
        assert kwargs["cc"] == ["single@example.com"]

    def test_from_name(self):
        msg = _make_message(extra={"from_name": "Alice Sender"})
        kwargs = outbound_to_ses_kwargs(msg, default_from_email=FROM_EMAIL)
        # formataddr produces '"Alice Sender" <sender@example.com>' or equivalent
        assert "Alice Sender" in kwargs["from_email"]
        assert FROM_EMAIL in kwargs["from_email"]

    def test_reply_to(self):
        msg = _make_message(extra={"reply_to": "reply@example.com"})
        kwargs = outbound_to_ses_kwargs(msg, default_from_email=FROM_EMAIL)
        assert kwargs["reply_to"] == ["reply@example.com"]

    # ── outbound_to_raw_mime ──

    def test_raw_mime_with_attachments(self):
        msg = _make_message(
            html_body="<b>Hi</b>",
            attachments=[
                {
                    "filename": "doc.pdf",
                    "content": b"PDF bytes here",
                    "content_type": "application/pdf",
                },
            ],
        )
        raw = outbound_to_raw_mime(msg, default_from_email=FROM_EMAIL)

        assert isinstance(raw, bytes)

        parsed = email.message_from_bytes(raw, policy=email_policy.default)
        assert parsed["Subject"] == "Test Subject"
        assert parsed["From"] == FROM_EMAIL
        assert parsed["To"] == "recipient@example.com"

        # Should be multipart/mixed with body + attachment
        assert parsed.get_content_type() == "multipart/mixed"

        # Find the attachment part
        parts = list(parsed.walk())
        filenames = [
            p.get_filename() for p in parts if p.get_filename()
        ]
        assert "doc.pdf" in filenames

    def test_raw_mime_cc_header(self):
        msg = _make_message(extra={"cc": ["cc@example.com"]})
        raw = outbound_to_raw_mime(msg, default_from_email=FROM_EMAIL)
        parsed = email.message_from_bytes(raw, policy=email_policy.default)
        assert "cc@example.com" in parsed["Cc"]

    def test_raw_mime_reply_to_header(self):
        msg = _make_message(extra={"reply_to": "reply@example.com"})
        raw = outbound_to_raw_mime(msg, default_from_email=FROM_EMAIL)
        parsed = email.message_from_bytes(raw, policy=email_policy.default)
        assert "reply@example.com" in parsed["Reply-To"]

    # ── ses_response_to_report ──

    def test_response_queued(self):
        response = {"MessageId": "ses-msg-abc123"}
        report = ses_response_to_report(response, "msg-1")

        assert report.status == DeliveryStatus.QUEUED
        assert report.message_id == "msg-1"
        assert report.extra["ses_message_id"] == "ses-msg-abc123"

    def test_response_no_message_id(self):
        report = ses_response_to_report({}, "msg-2")
        assert report.status == DeliveryStatus.QUEUED
        assert report.extra == {}


# ── TestSESAdapter ──


class TestSESAdapter:
    """Test SESEmailAdapter with mocked boto3."""

    def test_validate_credentials_valid(self, adapter):
        assert adapter.validate_credentials() is True

    def test_validate_credentials_missing_key(self, mock_boto3_session):
        from bapp_connectors.providers.email.ses.adapter import SESEmailAdapter

        a = SESEmailAdapter(
            credentials={"from_email": FROM_EMAIL},
        )
        assert a.validate_credentials() is False

    def test_test_connection_success(self, adapter):
        adapter.client.ses.get_account.return_value = {"SendQuota": {}}
        result = adapter.test_connection()
        assert result.success is True
        assert "Connected" in result.message

    def test_test_connection_failure(self, adapter):
        adapter.client.ses.get_account.side_effect = Exception("InvalidClientTokenId")
        result = adapter.test_connection()
        assert result.success is False

    def test_send_simple_email(self, adapter):
        adapter.client.ses.send_email.return_value = {"MessageId": "simple-123"}
        msg = _make_message(message_id="s1")
        report = adapter.send(msg)

        adapter.client.ses.send_email.assert_called_once()
        call_kwargs = adapter.client.ses.send_email.call_args[1]
        assert "Simple" in str(call_kwargs.get("Content", {}))
        assert report.status == DeliveryStatus.QUEUED
        assert report.message_id == "s1"

    def test_send_with_attachments_routes_to_raw(self, adapter):
        adapter.client.ses.send_email.return_value = {"MessageId": "raw-456"}
        msg = _make_message(
            message_id="r1",
            attachments=[
                {
                    "filename": "img.png",
                    "content": b"\x89PNG",
                    "content_type": "image/png",
                },
            ],
        )
        report = adapter.send(msg)

        adapter.client.ses.send_email.assert_called_once()
        call_kwargs = adapter.client.ses.send_email.call_args[1]
        assert "Raw" in str(call_kwargs.get("Content", {}))
        assert report.status == DeliveryStatus.QUEUED

    def test_send_bulk_returns_list(self, adapter):
        adapter.client.ses.send_email.return_value = {"MessageId": "bulk-1"}
        messages = [_make_message(message_id=f"b-{i}") for i in range(3)]
        reports = adapter.send_bulk(messages)

        assert len(reports) == 3
        assert all(isinstance(r, DeliveryReport) for r in reports)
        assert all(r.status == DeliveryStatus.QUEUED for r in reports)

    def test_send_error_returns_failed_report(self, adapter):
        adapter.client.ses.send_email.side_effect = Exception("MessageRejected: bad")
        msg = _make_message(message_id="e1")
        report = adapter.send(msg)

        assert report.status == DeliveryStatus.FAILED
        assert report.message_id == "e1"


# ── TestSESErrors ──


class TestSESErrors:
    """Test SES error classification."""

    def test_invalid_token(self):
        err = classify_ses_error(Exception("InvalidClientTokenId: bad key"))
        assert "authentication" in str(err).lower()

    def test_access_denied(self):
        err = classify_ses_error(Exception("AccessDeniedException: not allowed"))
        assert "authentication" in str(err).lower()

    def test_throttling(self):
        err = classify_ses_error(Exception("Throttling: rate exceeded"))
        assert isinstance(err, SESConnectionError)
        assert err.retryable is True

    def test_message_rejected(self):
        err = classify_ses_error(Exception("MessageRejected: Email address not verified"))
        assert isinstance(err, SESError)

    def test_generic_error(self):
        err = classify_ses_error(Exception("Something unexpected"))
        assert isinstance(err, SESError)
