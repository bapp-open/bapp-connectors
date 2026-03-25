"""
Google Drive storage adapter — implements StoragePort + OAuthCapability.
"""

from __future__ import annotations

import posixpath
from io import BytesIO
from typing import IO
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.google_drive.client import GoogleDriveApiClient
from bapp_connectors.providers.storage.google_drive.manifest import manifest

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleDriveStorageAdapter(StoragePort, OAuthCapability):
    """
    Google Drive storage adapter.

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
                provider_name="google_drive",
            )

        self.client = GoogleDriveApiClient(http_client=http_client)

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
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
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
        response = self.client.http.call(
            "POST",
            _GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
        )
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "refresh_token": refresh_token,
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
        directory = posixpath.dirname(name) or "/"
        file_name = posixpath.basename(name)
        folder_id = self.client.ensure_folder_path(directory)

        # Check if file already exists — update if so
        existing = self.client.find_by_path(name)
        if existing:
            self.client.update_file(existing, data)
            return name

        result = self.client.upload_file(data, file_name, folder_id)
        return result.get("name", name)

    def open(self, name: str) -> IO:
        file_id = self.client.find_by_path(name)
        if not file_id:
            raise FileNotFoundError(f"File not found: {name}")
        data = self.client.download_file(file_id)
        return BytesIO(data)

    def delete(self, name: str) -> None:
        try:
            file_id = self.client.find_by_path(name)
            if file_id:
                self.client.delete_file(file_id)
        except Exception:
            pass  # Django Storage.delete() should not raise

    def exists(self, name: str) -> bool:
        return self.client.find_by_path(name) is not None

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        folder_id = self.client.find_by_path(path) or "root"
        items = self.client.list_files(folder_id)
        dirs = []
        files = []
        for item in items:
            if item.get("mimeType") == "application/vnd.google-apps.folder":
                dirs.append(item.get("name", ""))
            else:
                files.append(item.get("name", ""))
        return dirs, files

    def size(self, name: str) -> int:
        file_id = self.client.find_by_path(name)
        if not file_id:
            return 0
        metadata = self.client.get_file_metadata(file_id)
        return int(metadata.get("size", 0))

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        folder_id = self.client.find_by_path(remote_path) or "root"
        items = self.client.list_files(folder_id)
        return [
            FileInfo(
                path=item.get("id", ""),
                name=item.get("name", ""),
                size=int(item.get("size", 0)),
                content_type=item.get("mimeType", ""),
                modified_at=item.get("modifiedTime", ""),
                is_directory=item.get("mimeType") == "application/vnd.google-apps.folder",
            )
            for item in items
        ]
