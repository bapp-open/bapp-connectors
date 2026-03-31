"""
Facebook Messenger unit tests — no network, webhook verification and parsing.

Tests: HMAC signature verification, verify challenge, inbound message parsing,
attachment/location extraction, webhook event parsing, credential validation.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, MessageChannel, OutboundMessage
from bapp_connectors.providers.messaging.messenger.adapter import MessengerMessagingAdapter
from bapp_connectors.providers.messaging.messenger.mappers import (
    build_payload,
    get_attachments_from_messenger,
    get_location_from_messenger,
    inbound_message_from_messenger,
    webhook_event_from_messenger,
)

PAGE_TOKEN = "test_page_token"
PAGE_ID = "123456789"
APP_SECRET = "test_app_secret"
VERIFY_TOKEN = "my_verify_token"


@pytest.fixture
def adapter():
    return MessengerMessagingAdapter(credentials={
        "page_access_token": PAGE_TOKEN,
        "page_id": PAGE_ID,
        "app_secret": APP_SECRET,
        "webhook_verify_token": VERIFY_TOKEN,
    })


def _sign_body(body: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ── Sample webhook payloads ──

SAMPLE_MESSAGE_WEBHOOK = {
    "object": "page",
    "entry": [{
        "id": PAGE_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "USER_PSID_123"},
            "recipient": {"id": PAGE_ID},
            "timestamp": 1700000000000,
            "message": {
                "mid": "m_abc123",
                "text": "Hello from Messenger!",
            },
        }],
    }],
}

SAMPLE_ATTACHMENT_WEBHOOK = {
    "object": "page",
    "entry": [{
        "id": PAGE_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "USER_PSID_123"},
            "recipient": {"id": PAGE_ID},
            "timestamp": 1700000000000,
            "message": {
                "mid": "m_img456",
                "attachments": [{
                    "type": "image",
                    "payload": {"url": "https://cdn.example.com/photo.jpg"},
                }],
            },
        }],
    }],
}

SAMPLE_LOCATION_WEBHOOK = {
    "object": "page",
    "entry": [{
        "id": PAGE_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "USER_PSID_123"},
            "recipient": {"id": PAGE_ID},
            "timestamp": 1700000000000,
            "message": {
                "mid": "m_loc789",
                "attachments": [{
                    "type": "location",
                    "title": "Pin",
                    "payload": {
                        "coordinates": {"lat": 44.4268, "long": 26.1025},
                    },
                }],
            },
        }],
    }],
}

SAMPLE_POSTBACK_WEBHOOK = {
    "object": "page",
    "entry": [{
        "id": PAGE_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "USER_PSID_123"},
            "recipient": {"id": PAGE_ID},
            "timestamp": 1700000000000,
            "postback": {
                "mid": "m_pb",
                "title": "Get Started",
                "payload": "GET_STARTED",
            },
        }],
    }],
}


# ── Contract Tests ──


class TestMessengerContract:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection_returns_result(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)


# ── Payload Building ──


class TestBuildPayload:

    def test_text_message(self):
        msg = OutboundMessage(channel=MessageChannel.OTHER, to="PSID_123", body="Hello")
        payload = build_payload(msg)
        assert payload["recipient"]["id"] == "PSID_123"
        assert payload["message"]["text"] == "Hello"

    def test_image_attachment(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to="PSID_123", body="",
            extra={"media_type": "image", "media_url": "https://example.com/photo.jpg"},
        )
        payload = build_payload(msg)
        assert payload["message"]["attachment"]["type"] == "image"
        assert payload["message"]["attachment"]["payload"]["url"] == "https://example.com/photo.jpg"

    def test_document_by_id(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to="PSID_123", body="",
            extra={"media_type": "document", "media_id": "att_12345"},
        )
        payload = build_payload(msg)
        assert payload["message"]["attachment"]["type"] == "file"
        assert payload["message"]["attachment"]["payload"]["attachment_id"] == "att_12345"

    def test_location_as_text(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to="PSID_123",
            extra={"location": {"latitude": 44.43, "longitude": 26.10, "name": "Bucharest"}},
        )
        payload = build_payload(msg)
        assert "44.43" in payload["message"]["text"]
        assert "Bucharest" in payload["message"]["text"]

    def test_contact_as_text(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to="PSID_123",
            extra={"contact": {"name": "John", "phone": "+40721000000"}},
        )
        payload = build_payload(msg)
        assert "John" in payload["message"]["text"]
        assert "+40721000000" in payload["message"]["text"]


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

    def test_missing_header(self, adapter):
        assert adapter.verify_webhook({}, b"{}") is False

    def test_no_app_secret(self):
        adapter = MessengerMessagingAdapter(credentials={
            "page_access_token": PAGE_TOKEN,
            "page_id": PAGE_ID,
        })
        assert adapter.verify_webhook({}, b"{}") is False


# ── Verify Challenge ──


class TestVerifyChallenge:

    def test_valid_challenge(self, adapter):
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "challenge_abc",
        }
        assert adapter.verify_challenge(params) == "challenge_abc"

    def test_wrong_token(self, adapter):
        params = {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x"}
        assert adapter.verify_challenge(params) is None

    def test_missing_params(self, adapter):
        assert adapter.verify_challenge({}) is None


# ── Inbound Message Parsing ──


class TestInboundMessage:

    def test_text_message(self):
        messaging = SAMPLE_MESSAGE_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_messenger(messaging)
        assert msg is not None
        assert msg.body == "Hello from Messenger!"
        assert msg.sender == "USER_PSID_123"
        assert msg.message_id == "m_abc123"

    def test_postback_returns_none(self):
        messaging = SAMPLE_POSTBACK_WEBHOOK["entry"][0]["messaging"][0]
        assert inbound_message_from_messenger(messaging) is None

    def test_timestamp_parsing(self):
        messaging = SAMPLE_MESSAGE_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_messenger(messaging)
        assert msg is not None
        assert msg.received_at is not None


# ── Attachment Extraction ──


class TestAttachments:

    def test_image_attachment(self):
        messaging = SAMPLE_ATTACHMENT_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_messenger(messaging)
        assert msg is not None
        attachments = get_attachments_from_messenger(msg)
        assert len(attachments) == 1
        assert attachments[0].type == "image"
        assert attachments[0].url == "https://cdn.example.com/photo.jpg"

    def test_text_has_no_attachments(self):
        messaging = SAMPLE_MESSAGE_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_messenger(messaging)
        assert msg is not None
        assert get_attachments_from_messenger(msg) == []


# ── Location Extraction ──


class TestLocation:

    def test_location_extraction(self):
        messaging = SAMPLE_LOCATION_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_messenger(messaging)
        assert msg is not None
        loc = get_location_from_messenger(msg)
        assert loc is not None
        assert loc.latitude == pytest.approx(44.4268)
        assert loc.longitude == pytest.approx(26.1025)

    def test_text_has_no_location(self):
        messaging = SAMPLE_MESSAGE_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_messenger(messaging)
        assert msg is not None
        assert get_location_from_messenger(msg) is None


# ── Webhook Event Parsing ──


class TestWebhookEvent:

    def test_message_webhook(self):
        event = webhook_event_from_messenger(SAMPLE_MESSAGE_WEBHOOK)
        assert event.provider == "messenger"
        assert event.provider_event_type == "messages"
        assert len(event.extra["inbound_messages"]) == 1
        assert event.extra["inbound_messages"][0]["body"] == "Hello from Messenger!"

    def test_postback_webhook(self):
        event = webhook_event_from_messenger(SAMPLE_POSTBACK_WEBHOOK)
        assert event.provider_event_type == "messaging_postbacks"
        assert event.extra["messaging_count"] == 1

    def test_parse_webhook_adapter(self, adapter):
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "messenger"

    def test_parse_webhook_invalid_json(self, adapter):
        from bapp_connectors.core.errors import WebhookVerificationError
        with pytest.raises(WebhookVerificationError):
            adapter.parse_webhook({}, b"not json")


# ── Credentials ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_page_token(self):
        adapter = MessengerMessagingAdapter(credentials={"page_id": PAGE_ID})
        assert adapter.validate_credentials() is False

    def test_missing_page_id(self):
        adapter = MessengerMessagingAdapter(credentials={"page_access_token": PAGE_TOKEN})
        assert adapter.validate_credentials() is False

    def test_app_secret_optional(self):
        adapter = MessengerMessagingAdapter(credentials={
            "page_access_token": PAGE_TOKEN,
            "page_id": PAGE_ID,
        })
        assert adapter.validate_credentials() is True
