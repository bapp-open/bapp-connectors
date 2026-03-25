"""
OneDrive OAuth and unit tests.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.providers.storage.onedrive.adapter import OneDriveStorageAdapter
from bapp_connectors.providers.storage.onedrive.manifest import manifest


class TestOneDriveOAuth:

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with OneDrive"
        assert len(manifest.auth.oauth.credential_fields) == 2
        assert "Files.ReadWrite" in manifest.auth.oauth.scopes
        assert "offline_access" in manifest.auth.oauth.scopes

    def test_get_authorize_url(self):
        adapter = OneDriveStorageAdapter(credentials={
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        })
        url = adapter.get_authorize_url("https://example.com/callback", state="abc123")
        assert "login.microsoftonline.com" in url
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=abc123" in url
        assert "scope=" in url

    def test_token_not_required_in_manifest(self):
        token_field = next(f for f in manifest.auth.required_fields if f.name == "token")
        assert token_field.required is False

    def test_adapter_can_be_created_without_token(self):
        adapter = OneDriveStorageAdapter(credentials={
            "client_id": "key",
            "client_secret": "secret",
        })
        assert adapter._client_id == "key"
        assert adapter._client_secret == "secret"

    def test_adapter_stores_default_folder_from_config(self):
        adapter = OneDriveStorageAdapter(
            credentials={"client_id": "key"},
            config={"default_folder": "/documents"},
        )
        assert adapter.default_folder == "/documents"


class TestOneDriveClient:

    def test_item_path_root(self):
        from bapp_connectors.providers.storage.onedrive.client import OneDriveApiClient
        assert OneDriveApiClient._item_path("/") == "root"
        assert OneDriveApiClient._item_path("") == "root"

    def test_item_path_file(self):
        from bapp_connectors.providers.storage.onedrive.client import OneDriveApiClient
        assert OneDriveApiClient._item_path("/docs/file.txt") == "root:/docs/file.txt:"
        assert OneDriveApiClient._item_path("docs/file.txt") == "root:/docs/file.txt:"

    def test_item_path_folder(self):
        from bapp_connectors.providers.storage.onedrive.client import OneDriveApiClient
        assert OneDriveApiClient._item_path("/photos/") == "root:/photos:"


class TestOneDriveManifest:

    def test_manifest_name(self):
        assert manifest.name == "onedrive"
        assert manifest.display_name == "OneDrive"

    def test_manifest_family(self):
        from bapp_connectors.core.types import ProviderFamily
        assert manifest.family == ProviderFamily.STORAGE

    def test_manifest_base_url(self):
        assert "graph.microsoft.com" in manifest.base_url
