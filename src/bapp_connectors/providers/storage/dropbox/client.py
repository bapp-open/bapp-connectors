"""
Dropbox API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with BearerAuth for the Dropbox API v2.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

# Dropbox uses a separate content endpoint for file uploads/downloads
DBX_CONTENT_BASE = "https://content.dropboxapi.com/2"


class DropboxApiClient:
    """
    Low-level Dropbox API client.

    This class only handles HTTP calls and response parsing.
    The base ResilientHttpClient points to https://api.dropboxapi.com/2/.
    File upload/download calls go to the content endpoint directly.
    """

    def __init__(self, http_client: ResilientHttpClient, default_folder: str = "/"):
        self.http = http_client
        self.default_folder = default_folder

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        return self.http.call(method, path, **kwargs)

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a Dropbox path. Root must be empty string, not '/'."""
        if not path or path == "/":
            return ""
        if not path.startswith("/"):
            path = "/" + path
        return path

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Test authentication by calling get_current_account."""
        try:
            self._call(
                "POST",
                "users/get_current_account",
                headers={"Content-Type": "application/json"},
                data="null",
            )
            return True
        except Exception:
            return False

    # ── File Operations ──

    def upload_file(self, file_data: bytes, file_name: str, remote_path: str) -> dict | list | str:
        """
        Upload a file to Dropbox.

        Uses the content upload endpoint directly (absolute URL).
        """
        directory = remote_path if remote_path else "/"
        if not directory.startswith("/"):
            directory = "/" + directory
        if not directory.endswith("/"):
            directory += "/"
        full_path = f"{directory}{file_name}"

        headers = {
            "Dropbox-API-Arg": json.dumps(
                {
                    "path": full_path,
                    "mode": "add",
                    "autorename": True,
                    "mute": False,
                    "strict_conflict": False,
                }
            ),
            "Content-Type": "application/octet-stream",
        }
        return self._call("POST", f"{DBX_CONTENT_BASE}/files/upload", headers=headers, data=file_data)

    def download_file(self, remote_path: str) -> bytes:
        """
        Download a file from Dropbox.

        Uses the content download endpoint directly (absolute URL).
        Returns the file content as bytes.
        """
        if not remote_path.startswith("/"):
            remote_path = "/" + remote_path

        headers = {
            "Dropbox-API-Arg": json.dumps({"path": remote_path}),
        }
        response = self.http.call(
            "POST",
            f"{DBX_CONTENT_BASE}/files/download",
            headers=headers,
            direct_response=True,
        )
        return response.content

    def delete_file(self, remote_path: str) -> dict | list | str:
        """Delete a file or folder from Dropbox."""
        if not remote_path.startswith("/"):
            remote_path = "/" + remote_path

        return self._call(
            "POST",
            "files/delete_v2",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"path": remote_path}),
        )

    def list_folder(self, remote_path: str = "/") -> list[dict[str, Any]]:
        """
        List files in a Dropbox folder.

        Handles pagination automatically.
        Returns a list of entry dicts from the Dropbox API.
        """
        path_arg = self._normalize_path(remote_path)

        payload = {
            "path": path_arg,
            "recursive": False,
            "include_deleted": False,
        }

        result = self._call(
            "POST",
            "files/list_folder",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
        )

        entries: list[dict[str, Any]] = []
        if isinstance(result, dict):
            entries.extend(result.get("entries", []))

            # Handle pagination
            while isinstance(result, dict) and result.get("has_more"):
                cursor = result.get("cursor")
                if not cursor:
                    break
                result = self._call(
                    "POST",
                    "files/list_folder/continue",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps({"cursor": cursor}),
                )
                if isinstance(result, dict):
                    entries.extend(result.get("entries", []))

        return entries
