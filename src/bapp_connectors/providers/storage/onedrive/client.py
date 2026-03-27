"""
OneDrive API client via Microsoft Graph — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with BearerAuth.
OneDrive supports path-based access: /root:/path/to/file:/
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class OneDriveApiClient:
    """Low-level OneDrive client via Microsoft Graph API."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        return self.http.call(method, path, **kwargs)

    @staticmethod
    def _item_path(path: str) -> str:
        """Build a Graph API path reference for a file/folder path.

        /foo/bar.txt -> root:/foo/bar.txt:
        / or empty  -> root
        """
        path = path.strip("/")
        if not path:
            return "root"
        return f"root:/{path}:"

    # ── Auth ──

    def test_auth(self) -> bool:
        try:
            self._call("GET", "root")
            return True
        except Exception:
            return False

    # ── Files ──

    def list_children(self, path: str = "/") -> list[dict]:
        item = self._item_path(path)
        endpoint = f"{item}/children" if item != "root" else "root/children"
        result = self._call("GET", endpoint)
        return result.get("value", []) if isinstance(result, dict) else []

    def get_item_metadata(self, path: str) -> dict:
        item = self._item_path(path)
        result = self._call("GET", item)
        return result if isinstance(result, dict) else {}

    def download_file(self, path: str) -> bytes:
        item = self._item_path(path)
        response = self.http.call("GET", f"{item}/content", direct_response=True)
        return response.content if hasattr(response, "content") else b""

    def upload_file(self, data: bytes, path: str) -> dict:
        """Upload a file (up to 4MB). For larger files, use upload sessions."""
        item = self._item_path(path)
        result = self.http.call(
            "PUT", f"{item}/content",
            headers={"Content-Type": "application/octet-stream"},
            data=data,
        )
        return result if isinstance(result, dict) else {}

    def create_folder(self, name: str, parent_path: str = "/") -> dict:
        parent = self._item_path(parent_path)
        endpoint = f"{parent}/children" if parent != "root" else "root/children"
        result = self._call("POST", endpoint, json={
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "rename",
        })
        return result if isinstance(result, dict) else {}

    def delete_item(self, item_id: str) -> None:
        self._call("DELETE", f"items/{item_id}")
