"""
Instagram DM unit tests — no network, webhook verification and parsing.

Tests: HMAC signature verification, verify challenge, inbound message parsing,
attachment extraction, echo filtering, webhook event parsing, credential validation.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, MessageChannel, OutboundMessage
from bapp_connectors.providers.messaging.instagram.adapter import InstagramMessagingAdapter
from bapp_connectors.providers.messaging.instagram.mappers import (
    build_payload,
    inbound_message_from_instagram,
    webhook_event_from_instagram,
)

PAGE_TOKEN = "test_page_token"
IG_USER_ID = "17841400000000"
APP_SECRET = "test_app_secret"
VERIFY_TOKEN = "my_verify_token"


@pytest.fixture
def adapter():
    return InstagramMessagingAdapter(credentials={
        "page_access_token": PAGE_TOKEN,
        "ig_user_id": IG_USER_ID,
        "app_secret": APP_SECRET,
        "webhook_verify_token": VERIFY_TOKEN,
    })


def _sign_body(body: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ── Sample webhook payloads ──

SAMPLE_MESSAGE_WEBHOOK = {
    "object": "instagram",
    "entry": [{
        "id": IG_USER_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "IGSID_123"},
            "recipient": {"id": IG_USER_ID},
            "timestamp": 1700000000000,
            "message": {
                "mid": "m_ig_abc123",
                "text": "Hello from Instagram DM!",
            },
        }],
    }],
}

SAMPLE_ECHO_WEBHOOK = {
    "object": "instagram",
    "entry": [{
        "id": IG_USER_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": IG_USER_ID},
            "recipient": {"id": "IGSID_123"},
            "timestamp": 1700000000000,
            "message": {
                "mid": "m_ig_echo",
                "text": "This is an echo",
                "is_echo": True,
            },
        }],
    }],
}

SAMPLE_ATTACHMENT_WEBHOOK = {
    "object": "instagram",
    "entry": [{
        "id": IG_USER_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "IGSID_123"},
            "recipient": {"id": IG_USER_ID},
            "timestamp": 1700000000000,
            "message": {
                "mid": "m_ig_img",
                "attachments": [{
                    "type": "image",
                    "payload": {"url": "https://cdn.instagram.com/photo.jpg"},
                }],
            },
        }],
    }],
}

SAMPLE_STORY_MENTION_WEBHOOK = {
    "object": "instagram",
    "entry": [{
        "id": IG_USER_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "IGSID_123"},
            "recipient": {"id": IG_USER_ID},
            "timestamp": 1700000000000,
            "message": {
                "mid": "m_ig_story",
                "attachments": [{
                    "type": "story_mention",
                    "payload": {"url": "https://cdn.instagram.com/story.jpg"},
                }],
            },
        }],
    }],
}

SAMPLE_REACTION_WEBHOOK = {
    "object": "instagram",
    "entry": [{
        "id": IG_USER_ID,
        "time": 1700000000000,
        "messaging": [{
            "sender": {"id": "IGSID_123"},
            "recipient": {"id": IG_USER_ID},
            "timestamp": 1700000000000,
            "reaction": {
                "mid": "m_ig_react",
                "action": "react",
                "reaction": "\u2764\ufe0f",
            },
        }],
    }],
}


# ── Contract Tests ──


class TestInstagramContract:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection_returns_result(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)


# ── Payload Building ──


class TestBuildPayload:

    def test_text_message(self):
        msg = OutboundMessage(channel=MessageChannel.OTHER, to="IGSID_123", body="Hello")
        payload = build_payload(msg)
        assert payload["recipient"]["id"] == "IGSID_123"
        assert payload["message"]["text"] == "Hello"

    def test_image_attachment(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to="IGSID_123", body="",
            extra={"media_type": "image", "media_url": "https://example.com/photo.jpg"},
        )
        payload = build_payload(msg)
        assert payload["message"]["attachment"]["type"] == "image"

    def test_story_reply(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to="IGSID_123", body="Nice story!",
            extra={"story_id": "story_456"},
        )
        payload = build_payload(msg)
        assert payload["message"]["reply_to"]["story_id"] == "story_456"

    def test_location_as_text(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to="IGSID_123",
            extra={"location": {"latitude": 44.43, "longitude": 26.10, "name": "Bucharest"}},
        )
        payload = build_payload(msg)
        assert "44.43" in payload["message"]["text"]


# ── Webhook Verification ──


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


# ── Verify Challenge ──


class TestVerifyChallenge:

    def test_valid_challenge(self, adapter):
        params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "abc123"}
        assert adapter.verify_challenge(params) == "abc123"

    def test_wrong_token(self, adapter):
        params = {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x"}
        assert adapter.verify_challenge(params) is None


# ── Inbound Message Parsing ──


class TestInboundMessage:

    def test_text_message(self):
        messaging = SAMPLE_MESSAGE_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_instagram(messaging)
        assert msg is not None
        assert msg.body == "Hello from Instagram DM!"
        assert msg.sender == "IGSID_123"
        assert msg.message_id == "m_ig_abc123"

    def test_echo_message_skipped(self):
        messaging = SAMPLE_ECHO_WEBHOOK["entry"][0]["messaging"][0]
        assert inbound_message_from_instagram(messaging) is None

    def test_image_attachment(self):
        messaging = SAMPLE_ATTACHMENT_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_instagram(messaging)
        assert msg is not None
        assert len(msg.attachments) == 1
        assert msg.attachments[0].type == "image"
        assert msg.attachments[0].url == "https://cdn.instagram.com/photo.jpg"

    def test_story_mention_attachment(self):
        messaging = SAMPLE_STORY_MENTION_WEBHOOK["entry"][0]["messaging"][0]
        msg = inbound_message_from_instagram(messaging)
        assert msg is not None
        assert len(msg.attachments) == 1
        assert msg.attachments[0].type == "story_mention"

    def test_reaction_returns_none(self):
        messaging = SAMPLE_REACTION_WEBHOOK["entry"][0]["messaging"][0]
        assert inbound_message_from_instagram(messaging) is None


# ── Webhook Event Parsing ──


class TestWebhookEvent:

    def test_message_webhook(self):
        event = webhook_event_from_instagram(SAMPLE_MESSAGE_WEBHOOK)
        assert event.provider == "instagram"
        assert event.provider_event_type == "messages"
        assert event.event_type == "message.received"
        assert len(event.extra["inbound_messages"]) == 1

    def test_echo_filtered_out(self):
        event = webhook_event_from_instagram(SAMPLE_ECHO_WEBHOOK)
        assert event.provider_event_type == "messages"
        assert len(event.extra["inbound_messages"]) == 0

    def test_reaction_webhook(self):
        event = webhook_event_from_instagram(SAMPLE_REACTION_WEBHOOK)
        assert event.provider_event_type == "message_reactions"

    def test_parse_webhook_adapter(self, adapter):
        body = json.dumps(SAMPLE_MESSAGE_WEBHOOK).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "instagram"

    def test_parse_webhook_invalid_json(self, adapter):
        from bapp_connectors.core.errors import WebhookVerificationError
        with pytest.raises(WebhookVerificationError):
            adapter.parse_webhook({}, b"not json")


# ── Credentials ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_page_token(self):
        adapter = InstagramMessagingAdapter(credentials={"ig_user_id": IG_USER_ID})
        assert adapter.validate_credentials() is False

    def test_missing_ig_user_id(self):
        adapter = InstagramMessagingAdapter(credentials={"page_access_token": PAGE_TOKEN})
        assert adapter.validate_credentials() is False

    def test_app_secret_optional(self):
        adapter = InstagramMessagingAdapter(credentials={
            "page_access_token": PAGE_TOKEN,
            "ig_user_id": IG_USER_ID,
        })
        assert adapter.validate_credentials() is True
