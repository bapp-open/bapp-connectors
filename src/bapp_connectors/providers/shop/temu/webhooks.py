"""Temu webhook messages: AES-CBC body, HMAC-SHA256 signature over headers + decrypted body.

Scheme (Webhook Integration Guide):
- body ``{"eventData": "<base64>"}``, AES-128-CBC/PKCS7 with key = IV = first 16 bytes of the
  app secret (UTF-8);
- signature = HMAC-SHA256(app_secret) over ``"".join(key + value)`` of the sorted pairs
  {``eventData`` (decrypted), ``x-tm-app-key``, ``x-tm-event-code``, ``x-tm-ext-param``,
  ``x-tm-timestamp``}, hex lowercase, sent in ``x-tm-signature``.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import hmac
import json

from bapp_connectors.core.dto.webhook import WebhookEvent, WebhookEventType
from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.providers.shop.temu.models import WebhookEventCode

SIGNED_HEADERS = ("x-tm-app-key", "x-tm-event-code", "x-tm-ext-param", "x-tm-timestamp")
SIGNATURE_HEADER = "x-tm-signature"

EVENT_MAP = {
    WebhookEventCode.ORDER_STATUS_CHANGE: WebhookEventType.ORDER_UPDATED,
    WebhookEventCode.LOGISTICS_ADDRESS_CHANGED: WebhookEventType.ORDER_UPDATED,
    WebhookEventCode.CANCEL_ORDER_STATUS_CHANGE: WebhookEventType.ORDER_CANCELLED,
    WebhookEventCode.AFTERSALES_STATUS_CHANGE: WebhookEventType.UNKNOWN,
}


def _key_iv(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    if len(raw) < 16:
        raise WebhookVerificationError("Temu webhook: app secret shorter than 16 bytes")
    return raw[:16]


def decrypt_event_data(ciphertext_b64: str, secret: str) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = _key_iv(secret)
    try:
        ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
        return plain.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise WebhookVerificationError(f"Temu webhook: cannot decrypt eventData: {exc}") from exc


def encrypt_event_data(plaintext: str, secret: str) -> str:
    """Inverse of `decrypt_event_data` (tests, local simulation)."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = _key_iv(secret)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")


def _header(headers: dict, name: str) -> str:
    lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
    value = lowered.get(name.lower())
    return "" if value is None else str(value)


def webhook_signature(secret: str, headers: dict, decrypted_event_data: str) -> str:
    params = {name: _header(headers, name) for name in SIGNED_HEADERS}
    params["eventData"] = decrypted_event_data
    base = "".join(f"{key}{params[key]}" for key in sorted(params))
    return hmac.new(secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_event(headers: dict, body: bytes, secret: str, app_key: str) -> WebhookEvent:
    """Decrypt, verify and normalise one Temu message. Never raises on a bad signature:
    `signature_valid` is False and the payload is empty."""
    event_code = _header(headers, "x-tm-event-code")
    timestamp = _header(headers, "x-tm-timestamp")
    received_at = datetime.datetime.now(tz=datetime.UTC)
    base_event = WebhookEvent(
        provider="temu",
        provider_event_type=event_code,
        event_type=EVENT_MAP.get(event_code, WebhookEventType.UNKNOWN),  # type: ignore[arg-type]
        received_at=received_at,
        signature_valid=False,
        extra={"app_key_matches": _header(headers, "x-tm-app-key") == app_key},
    )
    try:
        envelope = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
        cipher = envelope.get("eventData") if isinstance(envelope, dict) else None
        if not cipher:
            return base_event
        plain = decrypt_event_data(str(cipher), secret)
    except (ValueError, WebhookVerificationError):
        return base_event
    expected = webhook_signature(secret, headers, plain)
    if not hmac.compare_digest(expected, _header(headers, SIGNATURE_HEADER).lower()):
        return base_event
    try:
        payload = json.loads(plain)
    except ValueError:
        return base_event
    if not isinstance(payload, dict):
        payload = {"data": payload}
    external_id = str(payload.get("parentOrderSn") or payload.get("orderSn") or payload.get("parentAfterSalesSn") or "")
    payload = {**payload, "external_id": external_id, "id": external_id}
    key = f"{event_code}:{timestamp}:{external_id}"
    return base_event.model_copy(update={
        "event_id": key,
        "idempotency_key": key,
        "payload": payload,
        "signature_valid": True,
    })
