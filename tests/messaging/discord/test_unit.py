"""
Discord unit tests — no network, payload building and webhook parsing.

Tests: message payload building, inbound parsing, attachment extraction,
webhook event parsing, credential validation.
"""

from __future__ import annotations

import json

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, MessageChannel, OutboundMessage
from bapp_connectors.providers.messaging.discord.adapter import DiscordMessagingAdapter
from bapp_connectors.providers.messaging.discord.mappers import (
    build_payload,
    get_attachments_from_discord,
    inbound_message_from_discord,
    webhook_event_from_discord,
)

BOT_TOKEN = "test_bot_token"
APP_ID = "123456789"
PUBLIC_KEY = "abcdef1234567890" * 4  # 64 hex chars
CHANNEL_ID = "987654321"


@pytest.fixture
def adapter():
    return DiscordMessagingAdapter(
        credentials={
            "bot_token": BOT_TOKEN,
            "application_id": APP_ID,
            "public_key": PUBLIC_KEY,
        },
        config={"default_channel_id": CHANNEL_ID},
    )


# ── Sample events ──

SAMPLE_MESSAGE_EVENT = {
    "id": "msg_001",
    "channel_id": CHANNEL_ID,
    "author": {
        "id": "user_123",
        "username": "testuser",
        "global_name": "Test User",
        "discriminator": "0",
        "bot": False,
    },
    "content": "Hello from Discord!",
    "timestamp": "2023-11-14T12:00:00.000000+00:00",
    "attachments": [],
    "embeds": [],
}

SAMPLE_BOT_MESSAGE = {
    "id": "msg_002",
    "channel_id": CHANNEL_ID,
    "author": {"id": "bot_456", "username": "mybot", "bot": True},
    "content": "Bot reply",
    "timestamp": "2023-11-14T12:00:01.000000+00:00",
    "attachments": [],
}

SAMPLE_ATTACHMENT_EVENT = {
    "id": "msg_003",
    "channel_id": CHANNEL_ID,
    "author": {"id": "user_123", "username": "testuser", "bot": False},
    "content": "",
    "timestamp": "2023-11-14T12:00:02.000000+00:00",
    "attachments": [
        {
            "id": "att_001",
            "filename": "photo.jpg",
            "url": "https://cdn.discordapp.com/attachments/photo.jpg",
            "proxy_url": "https://media.discordapp.net/attachments/photo.jpg",
            "content_type": "image/jpeg",
            "size": 102400,
        },
        {
            "id": "att_002",
            "filename": "document.pdf",
            "url": "https://cdn.discordapp.com/attachments/document.pdf",
            "content_type": "application/pdf",
            "size": 51200,
        },
    ],
}

SAMPLE_INTERACTION = {
    "id": "interaction_001",
    "application_id": APP_ID,
    "type": 2,  # APPLICATION_COMMAND
    "channel_id": CHANNEL_ID,
    "token": "interaction_token_123",
    "data": {"name": "ping", "type": 1},
}

SAMPLE_PING = {
    "id": "ping_001",
    "application_id": APP_ID,
    "type": 1,  # PING
    "token": "",
}


# ── Contract Tests ──


class TestDiscordContract:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection_returns_result(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)


# ── Payload Building ──


class TestBuildPayload:

    def test_text_message(self):
        msg = OutboundMessage(channel=MessageChannel.OTHER, to=CHANNEL_ID, body="Hello Discord!")
        payload = build_payload(msg)
        assert payload["content"] == "Hello Discord!"

    def test_reply_message(self):
        msg = OutboundMessage(channel=MessageChannel.OTHER, to=CHANNEL_ID, body="Reply", reply_to="msg_001")
        payload = build_payload(msg)
        assert payload["message_reference"]["message_id"] == "msg_001"

    def test_media_url(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=CHANNEL_ID, body="",
            extra={"media_type": "image", "media_url": "https://example.com/img.png", "caption": "Check this"},
        )
        payload = build_payload(msg)
        assert "https://example.com/img.png" in payload["content"]
        assert "Check this" in payload["content"]

    def test_location_as_embed(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=CHANNEL_ID,
            extra={"location": {"latitude": 44.43, "longitude": 26.10, "name": "Bucharest"}},
        )
        payload = build_payload(msg)
        assert payload["embeds"][0]["title"] == "Bucharest"
        assert "google.com/maps" in payload["embeds"][0]["url"]

    def test_contact_as_embed(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=CHANNEL_ID,
            extra={"contact": {"name": "John", "phone": "+40721000000", "email": "john@example.com"}},
        )
        payload = build_payload(msg)
        assert payload["embeds"][0]["title"] == "John"
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        assert fields["Phone"] == "+40721000000"
        assert fields["Email"] == "john@example.com"

    def test_embeds_passthrough(self):
        embed = {"title": "Custom", "description": "test"}
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=CHANNEL_ID, body="",
            extra={"embeds": [embed]},
        )
        payload = build_payload(msg)
        assert payload["embeds"] == [embed]


# ── Inbound Message Parsing ──


class TestInboundMessage:

    def test_text_message(self):
        msg = inbound_message_from_discord(SAMPLE_MESSAGE_EVENT)
        assert msg is not None
        assert msg.body == "Hello from Discord!"
        assert msg.sender == "user_123"
        assert msg.extra["username"] == "testuser"
        assert msg.extra["channel_id"] == CHANNEL_ID

    def test_bot_message_skipped(self):
        assert inbound_message_from_discord(SAMPLE_BOT_MESSAGE) is None

    def test_timestamp_parsing(self):
        msg = inbound_message_from_discord(SAMPLE_MESSAGE_EVENT)
        assert msg is not None
        assert msg.received_at is not None
        assert msg.received_at.year == 2023


# ── Attachment Extraction ──


class TestAttachments:

    def test_image_and_document(self):
        msg = inbound_message_from_discord(SAMPLE_ATTACHMENT_EVENT)
        assert msg is not None
        assert len(msg.attachments) == 2
        assert msg.attachments[0].type == "image"
        assert msg.attachments[0].filename == "photo.jpg"
        assert msg.attachments[0].file_size == 102400
        assert msg.attachments[1].type == "document"
        assert msg.attachments[1].filename == "document.pdf"

    def test_text_has_no_attachments(self):
        msg = inbound_message_from_discord(SAMPLE_MESSAGE_EVENT)
        assert msg is not None
        assert msg.attachments == []


# ── Webhook Event Parsing ──


class TestWebhookEvent:

    def test_interaction_event(self):
        event = webhook_event_from_discord(SAMPLE_INTERACTION)
        assert event.provider == "discord"
        assert event.provider_event_type == "APPLICATION_COMMAND"
        assert event.extra["interaction_type"] == 2

    def test_ping_event(self):
        event = webhook_event_from_discord(SAMPLE_PING)
        assert event.provider_event_type == "PING"

    def test_message_event(self):
        event = webhook_event_from_discord(SAMPLE_MESSAGE_EVENT)
        assert event.provider_event_type == "MESSAGE_CREATE"
        assert len(event.extra["inbound_messages"]) == 1

    def test_parse_webhook_adapter(self, adapter):
        body = json.dumps(SAMPLE_INTERACTION).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "discord"

    def test_parse_webhook_invalid_json(self, adapter):
        from bapp_connectors.core.errors import WebhookVerificationError
        with pytest.raises(WebhookVerificationError):
            adapter.parse_webhook({}, b"not json")


# ── Credentials ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_bot_token(self):
        adapter = DiscordMessagingAdapter(credentials={"application_id": APP_ID})
        assert adapter.validate_credentials() is False

    def test_missing_app_id(self):
        adapter = DiscordMessagingAdapter(credentials={"bot_token": BOT_TOKEN})
        assert adapter.validate_credentials() is False

    def test_public_key_optional(self):
        adapter = DiscordMessagingAdapter(credentials={
            "bot_token": BOT_TOKEN,
            "application_id": APP_ID,
        })
        assert adapter.validate_credentials() is True
