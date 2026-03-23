"""Tests for the webhook dispatcher and signature verification."""

import hashlib
import hmac
import json

import pytest

from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.webhooks import WebhookDispatcher
from bapp_connectors.core.webhooks.signatures import HmacSha256Verifier, NoopVerifier, get_verifier


def test_noop_verifier():
    v = NoopVerifier()
    assert v.verify(b"anything", "", "") is True


def test_hmac_sha256_verifier():
    v = HmacSha256Verifier()
    body = b'{"event": "test"}'
    secret = "my-secret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert v.verify(body, sig, secret) is True
    assert v.verify(body, f"sha256={sig}", secret) is True
    assert v.verify(body, "wrong-sig", secret) is False


def test_get_verifier():
    assert isinstance(get_verifier(None), NoopVerifier)
    assert isinstance(get_verifier("hmac-sha256"), HmacSha256Verifier)
    assert isinstance(get_verifier("unknown"), NoopVerifier)


def test_dispatcher_receive():
    dispatcher = WebhookDispatcher()
    body = json.dumps({"event": "order.created", "id": "123"}).encode()
    event = dispatcher.receive(
        provider="trendyol",
        headers={},
        body=body,
    )
    assert event.provider == "trendyol"
    assert event.payload == {"event": "order.created", "id": "123"}
    assert event.idempotency_key.startswith("trendyol:")
    assert event.signature_valid is True


def test_dispatcher_signature_verification_fails():
    dispatcher = WebhookDispatcher()
    body = b'{"event": "test"}'
    with pytest.raises(WebhookVerificationError):
        dispatcher.receive(
            provider="test",
            headers={},
            body=body,
            signature_method="hmac-sha256",
            signature_header="X-Signature",
            secret="my-secret",
        )


def test_dispatcher_signature_verification_succeeds():
    dispatcher = WebhookDispatcher()
    body = b'{"event": "test"}'
    secret = "my-secret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    event = dispatcher.receive(
        provider="test",
        headers={"X-Signature": sig},
        body=body,
        signature_method="hmac-sha256",
        signature_header="X-Signature",
        secret=secret,
    )
    assert event.signature_valid is True


def test_dispatcher_idempotency():
    seen = set()

    def checker(key):
        if key in seen:
            return True
        seen.add(key)
        return False

    dispatcher = WebhookDispatcher(idempotency_checker=checker)
    body = b'{"test": true}'

    assert not dispatcher.is_duplicate(dispatcher.compute_idempotency_key("test", body))
    # First call registers the key
    key = dispatcher.compute_idempotency_key("test", body)
    seen.add(key)
    assert dispatcher.is_duplicate(key)


def test_dispatcher_compute_idempotency_key():
    key = WebhookDispatcher.compute_idempotency_key("provider", b"body")
    assert key.startswith("provider:")
    assert len(key) > 10
