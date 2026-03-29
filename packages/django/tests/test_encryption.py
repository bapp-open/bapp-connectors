"""Tests for the encryption module."""

from __future__ import annotations

import json

import pytest

from django_bapp_connectors.encryption import decrypt_value, encrypt_value, reset_fernet


class TestEncryptDecryptRoundTrip:
    def test_simple_dict(self):
        data = {"api_key": "sk-test-123", "secret": "my-secret"}
        encrypted = encrypt_value(data)
        decrypted = decrypt_value(encrypted)
        assert decrypted == data

    def test_nested_dict(self):
        data = {
            "oauth": {
                "access_token": "token-abc",
                "refresh_token": "refresh-xyz",
                "scopes": ["read", "write"],
            },
            "settings": {"timeout": 30, "retry": True},
        }
        encrypted = encrypt_value(data)
        decrypted = decrypt_value(encrypted)
        assert decrypted == data


class TestEncryptedOutputIsNotPlaintext:
    def test_encrypted_value_differs_from_plaintext(self):
        data = {"api_key": "sk-test-123"}
        encrypted = encrypt_value(data)
        plaintext = json.dumps(data)
        assert encrypted != plaintext
        assert "sk-test-123" not in encrypted


class TestResetFernet:
    def test_reset_clears_cached_instance_and_still_works(self):
        data = {"key": "value"}
        encrypted_before = encrypt_value(data)
        assert decrypt_value(encrypted_before) == data

        reset_fernet()

        # After reset, a new Fernet instance is created; round-trip still works
        encrypted_after = encrypt_value(data)
        assert decrypt_value(encrypted_after) == data
        # Previously encrypted data should still decrypt (same key derivation)
        assert decrypt_value(encrypted_before) == data


class TestKeyDerivedFromSecretKey:
    def test_uses_secret_key_when_encryption_key_is_empty(self, settings):
        """ENCRYPTION_KEY is empty in test settings, so SECRET_KEY is used."""
        assert settings.BAPP_CONNECTORS["ENCRYPTION_KEY"] == ""

        # Encryption should work without an explicit ENCRYPTION_KEY
        data = {"token": "derived-from-secret"}
        encrypted = encrypt_value(data)
        decrypted = decrypt_value(encrypted)
        assert decrypted == data
