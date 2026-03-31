"""
Matrix unit tests — no network, payload building and webhook parsing.

Tests: message payload building, inbound parsing, webhook verification,
location/attachment extraction, credential validation.
"""

from __future__ import annotations

import json

import pytest

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    MessageChannel,
    OutboundMessage,
)
from bapp_connectors.providers.messaging.matrix.adapter import MatrixMessagingAdapter
from bapp_connectors.providers.messaging.matrix.mappers import (
    build_payload,
    get_attachments_from_matrix,
    get_location_from_matrix,
    inbound_message_from_matrix,
    webhook_event_from_matrix,
)

ACCESS_TOKEN = "syt_test_token"
HOMESERVER = "https://matrix.example.com"
APPSERVICE_TOKEN = "hs_test_token"
ROOM_ID = "!testroom:example.com"


@pytest.fixture
def adapter():
    return MatrixMessagingAdapter(
        credentials={
            "access_token": ACCESS_TOKEN,
            "homeserver_url": HOMESERVER,
            "appservice_token": APPSERVICE_TOKEN,
        },
        config={"default_room_id": ROOM_ID},
    )


# ── Sample events ──

SAMPLE_TEXT_EVENT = {
    "type": "m.room.message",
    "event_id": "$event1:example.com",
    "room_id": ROOM_ID,
    "sender": "@alice:example.com",
    "origin_server_ts": 1700000000000,
    "content": {
        "msgtype": "m.text",
        "body": "Hello from Matrix!",
    },
}

SAMPLE_IMAGE_EVENT = {
    "type": "m.room.message",
    "event_id": "$event2:example.com",
    "room_id": ROOM_ID,
    "sender": "@alice:example.com",
    "origin_server_ts": 1700000000000,
    "content": {
        "msgtype": "m.image",
        "body": "photo.jpg",
        "url": "mxc://example.com/media123",
        "info": {"mimetype": "image/jpeg", "size": 102400},
    },
}

SAMPLE_LOCATION_EVENT = {
    "type": "m.room.message",
    "event_id": "$event3:example.com",
    "room_id": ROOM_ID,
    "sender": "@alice:example.com",
    "origin_server_ts": 1700000000000,
    "content": {
        "msgtype": "m.location",
        "body": "Big Ben",
        "geo_uri": "geo:51.5008,-0.1247",
    },
}

SAMPLE_APPSERVICE_TXN = {
    "events": [SAMPLE_TEXT_EVENT, SAMPLE_IMAGE_EVENT],
}


# ── Contract Tests ──


class TestMatrixContract:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection_returns_result(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)


# ── Payload Building ──


class TestBuildPayload:

    def test_text_message(self):
        msg = OutboundMessage(channel=MessageChannel.OTHER, to=ROOM_ID, body="Hello")
        payload = build_payload(msg)
        assert payload["msgtype"] == "m.text"
        assert payload["body"] == "Hello"

    def test_html_message(self):
        msg = OutboundMessage(channel=MessageChannel.OTHER, to=ROOM_ID, body="Hello", html_body="<b>Hello</b>")
        payload = build_payload(msg)
        assert payload["format"] == "org.matrix.custom.html"
        assert payload["formatted_body"] == "<b>Hello</b>"

    def test_media_message(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=ROOM_ID, body="",
            extra={"media_type": "image", "media_id": "mxc://example.com/abc", "caption": "Photo"},
        )
        payload = build_payload(msg)
        assert payload["msgtype"] == "m.image"
        assert payload["url"] == "mxc://example.com/abc"

    def test_location_message(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=ROOM_ID,
            extra={"location": {"latitude": 44.4268, "longitude": 26.1025, "name": "Bucharest"}},
        )
        payload = build_payload(msg)
        assert payload["msgtype"] == "m.location"
        assert payload["geo_uri"] == "geo:44.4268,26.1025"

    def test_contact_message(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=ROOM_ID,
            extra={"contact": {"name": "John Doe", "phone": "+40721000000"}},
        )
        payload = build_payload(msg)
        assert payload["msgtype"] == "m.text"
        assert "John Doe" in payload["body"]
        assert "+40721000000" in payload["body"]

    def test_document_message(self):
        msg = OutboundMessage(
            channel=MessageChannel.OTHER, to=ROOM_ID, body="",
            extra={"media_type": "document", "media_id": "mxc://example.com/doc", "filename": "report.pdf"},
        )
        payload = build_payload(msg)
        assert payload["msgtype"] == "m.file"
        assert payload["filename"] == "report.pdf"


# ── Inbound Message Parsing ──


class TestInboundMessage:

    def test_text_message(self):
        msg = inbound_message_from_matrix(SAMPLE_TEXT_EVENT)
        assert msg is not None
        assert msg.body == "Hello from Matrix!"
        assert msg.sender == "@alice:example.com"
        assert msg.extra["room_id"] == ROOM_ID
        assert msg.extra["msgtype"] == "m.text"

    def test_image_message(self):
        msg = inbound_message_from_matrix(SAMPLE_IMAGE_EVENT)
        assert msg is not None
        assert msg.extra["msgtype"] == "m.image"

    def test_non_message_event(self):
        event = {"type": "m.room.member", "event_id": "$e1", "sender": "@a:b", "content": {}}
        assert inbound_message_from_matrix(event) is None

    def test_timestamp_parsing(self):
        msg = inbound_message_from_matrix(SAMPLE_TEXT_EVENT)
        assert msg is not None
        assert msg.received_at is not None
        assert msg.received_at.year == 2023


# ── Attachment Extraction ──


class TestAttachments:

    def test_image_attachment(self):
        msg = inbound_message_from_matrix(SAMPLE_IMAGE_EVENT)
        assert msg is not None
        attachments = get_attachments_from_matrix(msg)
        assert len(attachments) == 1
        assert attachments[0].type == "image"
        assert attachments[0].media_id == "mxc://example.com/media123"
        assert attachments[0].mime_type == "image/jpeg"
        assert attachments[0].file_size == 102400

    def test_text_has_no_attachments(self):
        msg = inbound_message_from_matrix(SAMPLE_TEXT_EVENT)
        assert msg is not None
        assert get_attachments_from_matrix(msg) == []


# ── Location Extraction ──


class TestLocation:

    def test_location_extraction(self):
        msg = inbound_message_from_matrix(SAMPLE_LOCATION_EVENT)
        assert msg is not None
        loc = get_location_from_matrix(msg)
        assert loc is not None
        assert loc.latitude == pytest.approx(51.5008)
        assert loc.longitude == pytest.approx(-0.1247)
        assert loc.name == "Big Ben"

    def test_text_has_no_location(self):
        msg = inbound_message_from_matrix(SAMPLE_TEXT_EVENT)
        assert msg is not None
        assert get_location_from_matrix(msg) is None


# ── Webhook Verification ──


class TestWebhookVerification:

    def test_valid_bearer_token(self, adapter):
        headers = {"Authorization": f"Bearer {APPSERVICE_TOKEN}"}
        assert adapter.verify_webhook(headers, b"{}") is True

    def test_invalid_token(self, adapter):
        headers = {"Authorization": "Bearer wrong_token"}
        assert adapter.verify_webhook(headers, b"{}") is False

    def test_missing_header(self, adapter):
        assert adapter.verify_webhook({}, b"{}") is False

    def test_no_token_configured(self):
        adapter = MatrixMessagingAdapter(credentials={
            "access_token": ACCESS_TOKEN,
            "homeserver_url": HOMESERVER,
        })
        assert adapter.verify_webhook({}, b"{}") is True


# ── Webhook Event Parsing ──


class TestWebhookEvent:

    def test_appservice_transaction(self):
        event = webhook_event_from_matrix(SAMPLE_APPSERVICE_TXN)
        assert event.provider == "matrix"
        assert event.provider_event_type == "m.room.message"
        assert event.extra["events_count"] == 2
        assert len(event.extra["inbound_messages"]) == 2

    def test_single_event(self):
        event = webhook_event_from_matrix(SAMPLE_TEXT_EVENT)
        assert event.provider == "matrix"
        assert event.event_id == "$event1:example.com"
        assert len(event.extra["inbound_messages"]) == 1

    def test_parse_webhook_adapter(self, adapter):
        body = json.dumps(SAMPLE_APPSERVICE_TXN).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "matrix"

    def test_parse_webhook_invalid_json(self, adapter):
        from bapp_connectors.core.errors import WebhookVerificationError
        with pytest.raises(WebhookVerificationError):
            adapter.parse_webhook({}, b"not json")


# ── Credentials ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_access_token(self):
        adapter = MatrixMessagingAdapter(credentials={"homeserver_url": HOMESERVER})
        assert adapter.validate_credentials() is False

    def test_missing_homeserver(self):
        adapter = MatrixMessagingAdapter(credentials={"access_token": ACCESS_TOKEN})
        assert adapter.validate_credentials() is False

    def test_appservice_token_optional(self):
        adapter = MatrixMessagingAdapter(credentials={
            "access_token": ACCESS_TOKEN,
            "homeserver_url": HOMESERVER,
        })
        assert adapter.validate_credentials() is True
