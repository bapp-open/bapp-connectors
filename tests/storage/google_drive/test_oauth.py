"""
Google Drive OAuth and unit tests.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.providers.storage.google_drive.adapter import GoogleDriveStorageAdapter
from bapp_connectors.providers.storage.google_drive.manifest import manifest


class TestGoogleDriveOAuth:

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Google Drive"
        assert len(manifest.auth.oauth.credential_fields) == 2
        assert any("drive" in s for s in manifest.auth.oauth.scopes)

    def test_get_authorize_url(self):
        adapter = GoogleDriveStorageAdapter(credentials={
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        })
        url = adapter.get_authorize_url("https://example.com/callback", state="abc123")
        assert "accounts.google.com" in url
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=abc123" in url
        assert "access_type=offline" in url

    def test_token_not_required_in_manifest(self):
        token_field = next(f for f in manifest.auth.required_fields if f.name == "token")
        assert token_field.required is False

    def test_adapter_can_be_created_without_token(self):
        adapter = GoogleDriveStorageAdapter(credentials={
            "client_id": "key",
            "client_secret": "secret",
        })
        assert adapter._client_id == "key"
        assert adapter._client_secret == "secret"

    def test_adapter_stores_default_folder_from_config(self):
        adapter = GoogleDriveStorageAdapter(
            credentials={"client_id": "key"},
            config={"default_folder": "/my-files"},
        )
        assert adapter.default_folder == "/my-files"


class TestGoogleDriveClient:

    def test_path_cache_initialized(self):
        adapter = GoogleDriveStorageAdapter(credentials={"client_id": "key"})
        assert adapter.client._path_cache == {}

    def test_find_by_path_root(self):
        adapter = GoogleDriveStorageAdapter(credentials={"client_id": "key"})
        assert adapter.client.find_by_path("/") == "root"
        assert adapter.client.find_by_path("") == "root"


class TestGoogleDriveManifest:

    def test_manifest_name(self):
        assert manifest.name == "google_drive"
        assert manifest.display_name == "Google Drive"

    def test_manifest_family(self):
        from bapp_connectors.core.types import ProviderFamily
        assert manifest.family == ProviderFamily.STORAGE

    def test_manifest_base_url(self):
        assert "googleapis.com/drive/v3" in manifest.base_url
