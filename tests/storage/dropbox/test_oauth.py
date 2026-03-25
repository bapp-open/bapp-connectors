"""
Dropbox OAuth unit tests.

Tests the OAuthCapability implementation for the Dropbox OAuth2 flow.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.providers.storage.dropbox.adapter import DropboxStorageAdapter
from bapp_connectors.providers.storage.dropbox.manifest import manifest


class TestDropboxOAuth:

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Dropbox"
        assert len(manifest.auth.oauth.credential_fields) == 2  # app_key, app_secret

    def test_get_authorize_url(self):
        adapter = DropboxStorageAdapter(credentials={
            "app_key": "test_app_key",
            "app_secret": "test_app_secret",
        })
        url = adapter.get_authorize_url("https://example.com/callback", state="abc123")
        assert "dropbox.com/oauth2/authorize" in url
        assert "client_id=test_app_key" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=abc123" in url
        assert "token_access_type=offline" in url

    def test_adapter_stores_oauth_fields(self):
        adapter = DropboxStorageAdapter(credentials={
            "app_key": "my_key",
            "app_secret": "my_secret",
            "token": "my_token",
        })
        assert adapter._app_key == "my_key"
        assert adapter._app_secret == "my_secret"

    def test_token_not_required_in_manifest(self):
        """Token is optional — OAuth flow provides it."""
        token_field = next(f for f in manifest.auth.required_fields if f.name == "token")
        assert token_field.required is False

    def test_adapter_can_be_created_without_token(self):
        """For OAuth flow, adapter is created with just app_key/app_secret."""
        adapter = DropboxStorageAdapter(credentials={
            "app_key": "key",
            "app_secret": "secret",
        })
        assert adapter._app_key == "key"
