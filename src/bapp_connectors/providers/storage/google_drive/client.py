"""
Google Drive API v3 client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with BearerAuth.
File uploads go to a separate upload endpoint.
Google Drive is ID-based: files are identified by ID, not path.
"""

from __future__ import annotations

import json
import posixpath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_FILE_FIELDS = "id,name,mimeType,size,modifiedTime,parents"


class GoogleDriveApiClient:
    """Low-level Google Drive API v3 client."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client
        self._path_cache: dict[str, str] = {}

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        return self.http.call(method, path, **kwargs)

    # ── Auth ──

    def test_auth(self) -> bool:
        try:
            self._call("GET", "about", params={"fields": "user"})
            return True
        except Exception:
            return False

    # ── Files ──

    def list_files(self, folder_id: str = "root", extra_query: str = "") -> list[dict]:
        q = f"'{folder_id}' in parents and trashed=false"
        if extra_query:
            q += f" and {extra_query}"
        result = self._call("GET", "files", params={
            "q": q,
            "fields": f"files({_FILE_FIELDS})",
            "pageSize": 1000,
        })
        return result.get("files", []) if isinstance(result, dict) else []

    def get_file_metadata(self, file_id: str) -> dict:
        result = self._call("GET", f"files/{file_id}", params={"fields": _FILE_FIELDS})
        return result if isinstance(result, dict) else {}

    def download_file(self, file_id: str) -> bytes:
        response = self.http.call(
            "GET", f"files/{file_id}",
            params={"alt": "media"},
            direct_response=True,
        )
        return response.content if hasattr(response, "content") else b""

    def upload_file(self, data: bytes, name: str, parent_id: str = "root", mime_type: str = "application/octet-stream") -> dict:
        metadata = json.dumps({"name": name, "parents": [parent_id]})
        boundary = "bapp_boundary"
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--".encode()

        result = self.http.call(
            "POST",
            f"{_UPLOAD_BASE}/files?uploadType=multipart&fields={_FILE_FIELDS}",
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
        )
        return result if isinstance(result, dict) else {}

    def update_file(self, file_id: str, data: bytes, mime_type: str = "application/octet-stream") -> dict:
        result = self.http.call(
            "PATCH",
            f"{_UPLOAD_BASE}/files/{file_id}?uploadType=media&fields={_FILE_FIELDS}",
            headers={"Content-Type": mime_type},
            data=data,
        )
        return result if isinstance(result, dict) else {}

    def create_folder(self, name: str, parent_id: str = "root") -> dict:
        result = self._call("POST", "files", json={
            "name": name,
            "mimeType": _FOLDER_MIME,
            "parents": [parent_id],
        })
        return result if isinstance(result, dict) else {}

    def delete_file(self, file_id: str) -> None:
        self._call("DELETE", f"files/{file_id}")

    # ── Path resolution ──

    def find_by_path(self, path: str) -> str | None:
        """Resolve a path like /folder/file.txt to a Google Drive file ID. Returns None if not found."""
        path = path.strip("/")
        if not path:
            return "root"

        cache_key = path
        if cache_key in self._path_cache:
            return self._path_cache[cache_key]

        parts = path.split("/")
        current_id = "root"

        for part in parts:
            items = self.list_files(current_id, extra_query=f"name='{part}'")
            if not items:
                return None
            current_id = items[0]["id"]

        self._path_cache[cache_key] = current_id
        return current_id

    def ensure_folder_path(self, path: str) -> str:
        """Ensure all folders in path exist, creating as needed. Returns the final folder ID."""
        path = path.strip("/")
        if not path:
            return "root"

        parts = path.split("/")
        current_id = "root"
        built_path = ""

        for part in parts:
            built_path = f"{built_path}/{part}" if built_path else part
            if built_path in self._path_cache:
                current_id = self._path_cache[built_path]
                continue

            items = self.list_files(current_id, extra_query=f"name='{part}' and mimeType='{_FOLDER_MIME}'")
            if items:
                current_id = items[0]["id"]
            else:
                folder = self.create_folder(part, current_id)
                current_id = folder["id"]
            self._path_cache[built_path] = current_id

        return current_id
