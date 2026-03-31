"""
WhatsApp unit tests — no network, webhook verification and parsing.

Tests: HMAC signature verification, verify challenge, inbound message parsing,
webhook event parsing, credential validation.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, WebhookEventType
from bapp_connectors.providers.messaging.whatsapp.adapter import WhatsAppMessagingAdapter
from bapp_connectors.providers.messaging.whatsapp.mappers import (
    inbound_message_from_whatsapp,
    webhook_event_from_whatsapp,
)

TOKEN = "test_token"
PHONE_ID = "123456789"
APP_SECRET = "test_app_secret"
VERIFY_TOKEN = "my_verify_token"


@pytest.fixture
def adapter():
    return WhatsAppMessagingAdapter(credentials={
        "token": TOKEN,
        "phone_number_id": PHONE_ID,
        "app_secret": APP_SECRET,
        "webhook_verify_token": VERIFY_TOKEN,
    })


def _sign_body(body: bytes, secret: str = APP_SECRET) -> str:
    """Compute Meta's X-Hub-Signature-256 header value."""
    digest = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ── Sample webhook payloads ──

SAMPLE_MESSAGE_WEBHOOK = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "BIZ_ACCOUNT_ID",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "display_phone_number": "15551234567",
                    "phone_number_id": PHONE_ID,
                },
                "contacts": [{
                    "wa_id": "40721000000",
                    "profile": {"name": "Test User"},
                }],
                "messages": [{
                    "from": "40721000000",
                    "id": "wamid.HBgNNDA3MjEwMDAwMDAVAgA",
                    "timestamp": "1700000000",
                    "type": "text",
                    "text": {"body": "Hello from WhatsApp!"},
                }],
            },
        }],
    }],
}

SAMPLE_STATUS_WEBHOOK = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "BIZ_ACCOUNT_ID",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "display_phone_number": "15551234567",
                    "phone_number_id": PHONE_ID,
                },
                "statuses": [{
                    "id": "wamid.STATUS123",
                    "status": "delivered",
                    "timestamp": "1700000001",
                    "recipient_id": "40721000000",
                }],
            },
        }],
    }],
}


# ── Contract Tests ──


class TestWhatsAppContract:
    """WhatsApp requires live API — only run credential/connection tests."""

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection_returns_result(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)


# ── Webhook Signature Verification ──


class TestWebhookVerification:

    def test_valid_signature(self, adapter):
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        headers = {"X-Hub-Signature-256": _sign_body(body)}
        assert adapter.verify_webhook(headers, body) is True

    def test_invalid_signature(self, adapter):
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        headers = {"X-Hub-Signature-256": "sha256=invalid"}
        assert adapter.verify_webhook(headers, body) is False

    def test_missing_signature_header(self, adapter):
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        assert adapter.verify_webhook({}, body) is False

    def test_no_app_secret(self):
        adapter = WhatsAppMessagingAdapter(credentials={
            "token": TOKEN,
            "phone_number_id": PHONE_ID,
        })
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        headers = {"X-Hub-Signature-256": _sign_body(body)}
        assert adapter.verify_webhook(headers, body) is False

    def test_custom_secret_override(self, adapter):
        custom_secret = "override_secret"
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        headers = {"X-Hub-Signature-256": _sign_body(body, secret=custom_secret)}
        assert adapter.verify_webhook(headers, body, secret=custom_secret) is True


# ── Verify Challenge ──


class TestVerifyChallenge:

    def test_valid_challenge(self, adapter):
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "challenge_string_123",
        }
        assert adapter.verify_challenge(params) == "challenge_string_123"

    def test_wrong_token(self, adapter):
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "challenge_string_123",
        }
        assert adapter.verify_challenge(params) is None

    def test_wrong_mode(self, adapter):
        params = {
            "hub.mode": "unsubscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "challenge_string_123",
        }
        assert adapter.verify_challenge(params) is None

    def test_missing_params(self, adapter):
        assert adapter.verify_challenge({}) is None


# ── Inbound Message Parsing ──


class TestInboundMessage:

    def test_text_message(self):
        msg = {
            "from": "40721000000",
            "id": "wamid.123",
            "timestamp": "1700000000",
            "type": "text",
            "text": {"body": "Hello!"},
        }
        contacts = [{"wa_id": "40721000000", "profile": {"name": "Test User"}}]
        result = inbound_message_from_whatsapp(msg, contacts)
        assert result.sender == "40721000000"
        assert result.body == "Hello!"
        assert result.message_id == "wamid.123"
        assert result.extra["sender_name"] == "Test User"
        assert result.extra["message_type"] == "text"

    def test_image_message_with_caption(self):
        msg = {
            "from": "40721000000",
            "id": "wamid.456",
            "timestamp": "1700000000",
            "type": "image",
            "image": {"caption": "Check this out", "id": "media_123"},
        }
        result = inbound_message_from_whatsapp(msg)
        assert result.body == "Check this out"
        assert result.extra["message_type"] == "image"

    def test_image_message_without_caption(self):
        msg = {
            "from": "40721000000",
            "id": "wamid.789",
            "timestamp": "1700000000",
            "type": "image",
            "image": {"id": "media_123"},
        }
        result = inbound_message_from_whatsapp(msg)
        assert result.body == ""

    def test_timestamp_parsing(self):
        msg = {
            "from": "40721000000",
            "id": "wamid.ts",
            "timestamp": "1700000000",
            "type": "text",
            "text": {"body": "test"},
        }
        result = inbound_message_from_whatsapp(msg)
        assert result.received_at is not None
        assert result.received_at.year == 2023

    def test_no_contacts(self):
        msg = {
            "from": "40721000000",
            "id": "wamid.nc",
            "type": "text",
            "text": {"body": "test"},
        }
        result = inbound_message_from_whatsapp(msg)
        assert result.extra["sender_name"] == ""


# ── Webhook Event Parsing ──


class TestWebhookEvent:

    def test_message_webhook(self):
        event = webhook_event_from_whatsapp(SAMPLE_MESSAGE_WEBHOOK)
        assert event.provider == "whatsapp"
        assert event.provider_event_type == "messages"
        assert event.event_id == "wamid.HBgNNDA3MjEwMDAwMDAVAgA"
        assert len(event.extra["inbound_messages"]) == 1
        assert event.extra["inbound_messages"][0]["body"] == "Hello from WhatsApp!"

    def test_status_webhook(self):
        event = webhook_event_from_whatsapp(SAMPLE_STATUS_WEBHOOK)
        assert event.provider == "whatsapp"
        assert event.provider_event_type == "message_status"
        assert event.event_id == "wamid.STATUS123"
        assert len(event.extra["statuses"]) == 1
        assert event.extra["statuses"][0]["status"] == "delivered"

    def test_empty_webhook(self):
        event = webhook_event_from_whatsapp({"object": "whatsapp_business_account", "entry": []})
        assert event.provider == "whatsapp"
        assert event.provider_event_type == "unknown"

    def test_parse_webhook_adapter(self, adapter):
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "whatsapp"
        assert event.provider_event_type == "messages"

    def test_parse_webhook_invalid_json(self, adapter):
        from bapp_connectors.core.errors import WebhookVerificationError
        with pytest.raises(WebhookVerificationError):
            adapter.parse_webhook({}, b"not json")


# ── Credentials ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_token(self):
        adapter = WhatsAppMessagingAdapter(credentials={"phone_number_id": PHONE_ID})
        assert adapter.validate_credentials() is False

    def test_missing_phone_id(self):
        adapter = WhatsAppMessagingAdapter(credentials={"token": TOKEN})
        assert adapter.validate_credentials() is False

    def test_app_secret_optional(self):
        """app_secret and webhook_verify_token are optional — credentials still valid without them."""
        adapter = WhatsAppMessagingAdapter(credentials={
            "token": TOKEN,
            "phone_number_id": PHONE_ID,
        })
        assert adapter.validate_credentials() is True
