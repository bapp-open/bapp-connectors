"""
Dropbox storage adapter — implements StoragePort + OAuthCapability.

This is the main entry point for the Dropbox integration.
"""

from __future__ import annotations

import posixpath
from io import BytesIO
from typing import IO
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.dropbox.client import DropboxApiClient
from bapp_connectors.providers.storage.dropbox.manifest import manifest

_DBX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
_DBX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


class DropboxStorageAdapter(StoragePort, OAuthCapability):
    """
    Dropbox storage adapter.

    Implements:
    - StoragePort: save, open, delete, exists, listdir, size, list_files
    - OAuthCapability: OAuth2 authorization code flow with refresh tokens
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.default_folder = credentials.get("default_folder", "/")
        self._app_key = credentials.get("app_key", "")
        self._app_secret = credentials.get("app_secret", "")

        if http_client is None:
            from bapp_connectors.core.http import BearerAuth

            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="dropbox",
            )

        self.client = DropboxApiClient(
            http_client=http_client,
            default_folder=self.default_folder,
        )

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
        params = {
            "client_id": self._app_key,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "token_access_type": "offline",
        }
        return f"{_DBX_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _DBX_TOKEN_URL,
            data={
                "code": code,
                "grant_type": "authorization_code",
                "client_id": self._app_key,
                "client_secret": self._app_secret,
                "redirect_uri": redirect_uri,
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
                    "app_key": self._app_key,
                    "app_secret": self._app_secret,
                    "refresh_token": refresh_tok,
                },
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _DBX_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "client_id": self._app_key,
                "client_secret": self._app_secret,
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
                    "app_key": self._app_key,
                    "app_secret": self._app_secret,
                    "refresh_token": refresh_token,
                },
            },
        )

    # ── StoragePort (Django Storage API) ──

    def save(self, name: str, content: bytes | IO) -> str:
        if isinstance(content, bytes):
            data = content
        else:
            data = content.read()
        directory = posixpath.dirname(name) or "/"
        file_name = posixpath.basename(name)
        result = self.client.upload_file(data, file_name, directory)
        if isinstance(result, dict):
            return result.get("path_display", name)
        return name

    def open(self, name: str) -> IO:
        data = self.client.download_file(name)
        return BytesIO(data)

    def delete(self, name: str) -> None:
        try:
            self.client.delete_file(name)
        except Exception:
            pass  # Django Storage.delete() should not raise if file doesn't exist

    def exists(self, name: str) -> bool:
        try:
            # Dropbox doesn't have a direct "exists" — try to get metadata
            import json
            self.client._call(
                "POST", "files/get_metadata",
                headers={"Content-Type": "application/json"},
                data=json.dumps({"path": name if name.startswith("/") else "/" + name}),
            )
            return True
        except Exception:
            return False

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        entries = self.client.list_folder(path)
        dirs = []
        files = []
        for entry in entries:
            name = entry.get("name", "")
            if entry.get(".tag") == "folder":
                dirs.append(name)
            else:
                files.append(name)
        return dirs, files

    def size(self, name: str) -> int:
        try:
            import json
            result = self.client._call(
                "POST", "files/get_metadata",
                headers={"Content-Type": "application/json"},
                data=json.dumps({"path": name if name.startswith("/") else "/" + name}),
            )
            if isinstance(result, dict):
                return result.get("size", 0)
        except Exception:
            pass
        return 0

    # ── Convenience overrides with richer metadata ──

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        entries = self.client.list_folder(remote_path)
        return [
            FileInfo(
                path=entry.get("path_display", ""),
                name=entry.get("name", ""),
                size=entry.get("size", 0),
                content_type="",
                modified_at=entry.get("server_modified", ""),
                is_directory=entry.get(".tag") == "folder",
            )
            for entry in entries
        ]
