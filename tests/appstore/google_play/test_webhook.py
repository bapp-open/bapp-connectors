"""Push Pub/Sub: parsare RTDN si verificare OIDC optionala."""

from __future__ import annotations

import base64
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from bapp_connectors.core.dto import WebhookEventType
from bapp_connectors.providers.appstore.google_play.adapter import GooglePlayAdapter
from bapp_connectors.providers.appstore.google_play.errors import GooglePlayWebhookError
from tests.appstore.google_play.test_unit import CREDENTIALS
from tests.fake_http import FakeHttpClient


def _body(rtdn: dict, message_id: str = "m1") -> bytes:
    data = base64.b64encode(json.dumps(rtdn).encode()).decode()
    return json.dumps({"message": {"data": data, "messageId": message_id, "publishTime": "2026-09-10T10:00:00Z"}, "subscription": "projects/p/subscriptions/s"}).encode()


@pytest.fixture
def rsa_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()

    def b64(n: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode().rstrip("=")

    jwks = {"keys": [{"kty": "RSA", "kid": "k1", "alg": "RS256", "use": "sig", "n": b64(numbers.n), "e": b64(numbers.e)}]}
    return key, jwks


def _adapter(fake_http, audience: str = ""):
    creds = {**CREDENTIALS, "pubsub_audience": audience}
    a = GooglePlayAdapter(credentials=creds, http_client=fake_http)
    a.auth._fetch = lambda uri, assertion: {"access_token": "t", "expires_in": 3600}
    return a


def test_parse_subscription_notification():
    adapter = _adapter(FakeHttpClient())
    body = _body({"version": "1.0", "packageName": "ro.cbsoft.app", "eventTimeMillis": "1789120800000", "subscriptionNotification": {"version": "1.0", "notificationType": 2, "purchaseToken": "tok", "subscriptionId": "pro_monthly"}})
    event = adapter.parse_webhook({}, body)
    assert event.event_type == WebhookEventType.SUBSCRIPTION_RENEWED
    assert event.idempotency_key == "m1"
    assert event.payload == {"purchase_token": "tok", "product_id": "pro_monthly", "package_name": "ro.cbsoft.app"}


def test_parse_voided_purchase_notification():
    adapter = _adapter(FakeHttpClient())
    body = _body({"version": "1.0", "packageName": "ro.cbsoft.app", "voidedPurchaseNotification": {"purchaseToken": "tok", "orderId": "GPA.1", "productType": 1, "refundType": 1}})
    assert adapter.parse_webhook({}, body).event_type == WebhookEventType.PURCHASE_REFUNDED


def test_parse_rejects_non_pubsub_body():
    adapter = _adapter(FakeHttpClient())
    with pytest.raises(GooglePlayWebhookError):
        adapter.parse_webhook({}, b'{"foo": 1}')


def test_verify_without_audience_accepts():
    adapter = _adapter(FakeHttpClient())
    assert adapter.verify_webhook({}, _body({"packageName": "x"})) is True


def test_verify_with_audience_checks_oidc_token(rsa_key):
    key, jwks = rsa_key
    fake = FakeHttpClient()
    fake.add("GET", "oauth2/v3/certs", jwks)
    adapter = _adapter(fake, audience="https://bapp.example/hook/1")
    good = jwt.encode({"iss": "https://accounts.google.com", "aud": "https://bapp.example/hook/1", "email": "sa@p.iam.gserviceaccount.com", "exp": 4_000_000_000}, key, algorithm="RS256", headers={"kid": "k1"})
    assert adapter.verify_webhook({"Authorization": f"Bearer {good}"}, _body({"packageName": "x"})) is True
    bad_aud = jwt.encode({"iss": "https://accounts.google.com", "aud": "https://other", "exp": 4_000_000_000}, key, algorithm="RS256", headers={"kid": "k1"})
    assert adapter.verify_webhook({"Authorization": f"Bearer {bad_aud}"}, _body({"packageName": "x"})) is False
    assert adapter.verify_webhook({}, _body({"packageName": "x"})) is False
