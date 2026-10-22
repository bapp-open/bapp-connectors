import json

import pytest

pytest.importorskip("cryptography")

from bapp_connectors.core.dto.webhook import WebhookEventType
from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.webhooks.signatures import ADAPTER_VERIFIED_METHODS
from bapp_connectors.providers.shop.temu.adapter import TemuShopAdapter
from bapp_connectors.providers.shop.temu.manifest import WEBHOOK_SIGNATURE_METHOD, manifest
from bapp_connectors.providers.shop.temu.webhooks import (
    decrypt_event_data,
    encrypt_event_data,
    parse_event,
    webhook_signature,
)
from tests.shop.temu.conftest import ok

# Vectors from Temu's "Webhook Integration Guide" (test app, test secret).
SECRET = "12345678abcdefgh"
CIPHER = "sQmNTAKR2o4HrmCO3OchFgGyJU5Qta57+JQxxgVyVPU="
PLAIN = '{"orderSn":"XXYYZZ","status":1}'
HEADERS = {
    "x-tm-app-key": "demo-test-app",
    "x-tm-event-code": "bg_test_event",
    "x-tm-ext-param": "{}",
    "x-tm-timestamp": "1726127013525",
    "x-tm-signature": "b5143d1a831453afbcf76d4621baa74a2dc07a486f26f5a956c6e50c61a338fb",
}
BODY = json.dumps({"eventData": CIPHER}).encode()


def test_decrypt_documented_vector():
    assert decrypt_event_data(CIPHER, SECRET) == PLAIN


def test_encrypt_round_trip_with_long_secret():
    secret = "c7e0a1a63542be4de3cb5488f9fba8149e8fc290"
    assert decrypt_event_data(encrypt_event_data('{"a": "ă"}', secret), secret) == '{"a": "ă"}'


def test_signature_documented_vector():
    assert webhook_signature(SECRET, HEADERS, PLAIN) == HEADERS["x-tm-signature"]


def test_signature_header_lookup_is_case_insensitive():
    upper = {k.upper(): v for k, v in HEADERS.items()}
    assert webhook_signature(SECRET, upper, PLAIN) == HEADERS["x-tm-signature"]


def test_parse_event_valid():
    ev = parse_event(HEADERS, BODY, SECRET, "demo-test-app")
    assert ev.signature_valid is True and ev.payload["orderSn"] == "XXYYZZ"
    assert ev.payload["external_id"] == ev.payload["id"] == "XXYYZZ"
    assert ev.provider == "temu" and ev.provider_event_type == "bg_test_event"
    assert ev.idempotency_key == "bg_test_event:1726127013525:XXYYZZ" and ev.event_id == ev.idempotency_key
    assert ev.received_at is not None and ev.extra["app_key_matches"] is True


def test_parse_event_prefers_parent_order_sn():
    plain = '{"parentOrderSn":"PO-1","orderSn":"1-1","status":4}'
    body = json.dumps({"eventData": encrypt_event_data(plain, SECRET)}).encode()
    headers = {**HEADERS, "x-tm-event-code": "bg_order_status_change_event"}
    headers["x-tm-signature"] = webhook_signature(SECRET, headers, plain)
    ev = parse_event(headers, body, SECRET, "demo-test-app")
    assert ev.payload["id"] == "PO-1" and ev.event_type == WebhookEventType.ORDER_UPDATED


def test_verify_rejects_wrong_secret():
    ev = parse_event(HEADERS, BODY, "0000000000000000", "demo-test-app")
    assert ev.signature_valid is False and ev.payload == {} and ev.event_type == WebhookEventType.UNKNOWN


def test_verify_rejects_tampered_signature():
    assert parse_event({**HEADERS, "x-tm-signature": "00"}, BODY, SECRET, "demo-test-app").signature_valid is False


def test_verify_rejects_foreign_app_key():
    ev = parse_event(HEADERS, BODY, SECRET, "another-app")
    assert ev.signature_valid is True and ev.extra["app_key_matches"] is False


def test_verify_rejects_garbage_body():
    with pytest.raises(WebhookVerificationError):
        decrypt_event_data("not base64!!", SECRET)
    with pytest.raises(WebhookVerificationError):
        decrypt_event_data(CIPHER, "x")  # key shorter than 16 bytes


def test_parse_event_without_event_data_is_invalid():
    ev = parse_event(HEADERS, b'{"other": 1}', SECRET, "demo-test-app")
    assert ev.signature_valid is False


def test_event_map_and_registry_method():
    assert WEBHOOK_SIGNATURE_METHOD in ADAPTER_VERIFIED_METHODS and manifest.webhooks.signature_method == WEBHOOK_SIGNATURE_METHOD
    ev = parse_event({**HEADERS, "x-tm-event-code": "bg_cancel_order_status_change"}, BODY, SECRET, "demo-test-app")
    assert ev.event_type == WebhookEventType.ORDER_CANCELLED and ev.signature_valid is False  # code changed → signature no longer matches
    ev = parse_event({**HEADERS, "x-tm-event-code": "bg_aftersales_status_change"}, BODY, SECRET, "demo-test-app")
    assert ev.event_type == WebhookEventType.UNKNOWN and ev.provider_event_type == "bg_aftersales_status_change"


def test_adapter_verify_uses_its_own_secret(fake):
    adapter = TemuShopAdapter({"app_key": "demo-test-app", "app_secret": SECRET, "access_token": "t"}, http_client=fake, config={})
    assert adapter.verify_webhook(HEADERS, BODY) is True
    assert adapter.verify_webhook(HEADERS, BODY, secret="ignored") is True
    other = TemuShopAdapter({"app_key": "other-app", "app_secret": SECRET, "access_token": "t"}, http_client=fake, config={})
    assert other.verify_webhook(HEADERS, BODY) is False
    assert adapter.parse_webhook(HEADERS, BODY).payload["id"] == "XXYYZZ"


def test_register_webhook_activates_events(fake):
    adapter = TemuShopAdapter({"app_key": "k", "app_secret": SECRET, "access_token": "t"}, http_client=fake, config={})
    fake.add("POST", "openapi/router", ok({}))
    out = adapter.register_webhook("https://host.example.test/webhooks/1/temu/")
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.tmc.message.update" and body["permitEventCodeList"] == manifest.webhooks.events
    assert out["permitted"] == manifest.webhooks.events and "Partner Platform" in out["url_note"]
    assert adapter.list_webhooks() == [{"event": e} for e in manifest.webhooks.events]
