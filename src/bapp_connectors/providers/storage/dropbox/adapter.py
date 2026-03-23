"""
Dropbox storage adapter — implements StoragePort.

This is the main entry point for the Dropbox integration.
"""

from __future__ import annotations

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.dropbox.client import DropboxApiClient
from bapp_connectors.providers.storage.dropbox.manifest import manifest


class DropboxStorageAdapter(StoragePort):
    """
    Dropbox storage adapter.

    Implements:
    - StoragePort: upload, download, delete, list_files
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, **kwargs):
        self.credentials = credentials
        self.default_folder = credentials.get("default_folder", "/")

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

    # ── StoragePort ──

    def upload(self, file_data: bytes, file_name: str, remote_path: str) -> str:
        """Upload a file to Dropbox. Returns the remote path."""
        result = self.client.upload_file(file_data, file_name, remote_path)
        if isinstance(result, dict):
            return result.get("path_display", f"{remote_path}/{file_name}")
        return f"{remote_path}/{file_name}"

    def download(self, remote_path: str) -> bytes:
        """Download a file from Dropbox. Returns file bytes."""
        return self.client.download_file(remote_path)

    def delete(self, remote_path: str) -> bool:
        """Delete a file from Dropbox. Returns True if successful."""
        try:
            self.client.delete_file(remote_path)
            return True
        except Exception:
            return False

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        """List files in a Dropbox directory."""
        entries = self.client.list_folder(remote_path)
        files = []
        for entry in entries:
            tag = entry.get(".tag", "")
            files.append(
                FileInfo(
                    path=entry.get("path_display", ""),
                    name=entry.get("name", ""),
                    size=entry.get("size", 0),
                    content_type="",
                    modified_at=entry.get("server_modified", ""),
                    is_directory=tag == "folder",
                )
            )
        return files
