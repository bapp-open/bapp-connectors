"""
Credential encryption using Fernet (symmetric encryption).

Uses the BAPP_CONNECTORS["ENCRYPTION_KEY"] setting as the Fernet key.
Falls back to Django's SECRET_KEY if no explicit key is set.
"""

from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet

_fernet_instance = None


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        from django_bapp_connectors.settings import get_setting
        from django.conf import settings

        key = get_setting("ENCRYPTION_KEY")
        if not key:
            # Derive a Fernet-compatible key from Django's SECRET_KEY
            raw = settings.SECRET_KEY.encode()
            key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        elif isinstance(key, str):
            key = key.encode()

        _fernet_instance = Fernet(key)
    return _fernet_instance


def encrypt_value(data: dict) -> str:
    """Encrypt a dict to a Fernet-encrypted string."""
    plaintext = json.dumps(data).encode()
    return _get_fernet().encrypt(plaintext).decode()


def decrypt_value(encrypted: str) -> dict:
    """Decrypt a Fernet-encrypted string back to a dict."""
    plaintext = _get_fernet().decrypt(encrypted.encode())
    return json.loads(plaintext)


def reset_fernet():
    """Reset the cached Fernet instance (for testing)."""
    global _fernet_instance
    _fernet_instance = None
