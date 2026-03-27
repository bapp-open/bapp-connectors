"""
OneDrive storage adapter — implements StoragePort + OAuthCapability.

Uses Microsoft Graph API v1.0 with path-based file access.
"""

from __future__ import annotations

from io import BytesIO
from typing import IO
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.onedrive.client import OneDriveApiClient
from bapp_connectors.providers.storage.onedrive.manifest import manifest

_MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
_MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


class OneDriveStorageAdapter(StoragePort, OAuthCapability):
    """
    OneDrive storage adapter via Microsoft Graph.

    Implements:
    - StoragePort: save, open, delete, exists, listdir, size, list_files
    - OAuthCapability: OAuth2 authorization code flow with refresh tokens
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self.default_folder = config.get("default_folder", "/")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="onedrive",
            )

        self.client = OneDriveApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
        }
        return f"{_MS_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        response = self.client.http.call(
            "POST",
            _MS_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": " ".join(scopes),
            },
        )
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        refresh_tok = data.get("refresh_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_tok,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "refresh_token": refresh_tok,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        response = self.client.http.call(
            "POST",
            _MS_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "scope": " ".join(scopes),
            },
        )
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        new_refresh = data.get("refresh_token", refresh_token)
        return OAuthTokens(
            access_token=access_token,
            refresh_token=new_refresh,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "refresh_token": new_refresh,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            },
        )

    # ── StoragePort ──

    def save(self, name: str, content: bytes | IO) -> str:
        if isinstance(content, bytes):
            data = content
        else:
            data = content.read()
        # OneDrive PUT to path creates or overwrites
        result = self.client.upload_file(data, name)
        return result.get("name", name)

    def open(self, name: str) -> IO:
        data = self.client.download_file(name)
        return BytesIO(data)

    def delete(self, name: str) -> None:
        try:
            metadata = self.client.get_item_metadata(name)
            item_id = metadata.get("id")
            if item_id:
                self.client.delete_item(item_id)
        except Exception:
            pass  # Django Storage.delete() should not raise

    def exists(self, name: str) -> bool:
        try:
            metadata = self.client.get_item_metadata(name)
            return bool(metadata.get("id"))
        except Exception:
            return False

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        items = self.client.list_children(path)
        dirs = []
        files = []
        for item in items:
            name = item.get("name", "")
            if "folder" in item:
                dirs.append(name)
            else:
                files.append(name)
        return dirs, files

    def size(self, name: str) -> int:
        try:
            metadata = self.client.get_item_metadata(name)
            return metadata.get("size", 0)
        except Exception:
            return 0

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        items = self.client.list_children(remote_path)
        return [
            FileInfo(
                path=item.get("id", ""),
                name=item.get("name", ""),
                size=item.get("size", 0),
                content_type=item.get("file", {}).get("mimeType", "") if "file" in item else "",
                modified_at=item.get("lastModifiedDateTime", ""),
                is_directory="folder" in item,
            )
            for item in items
        ]
