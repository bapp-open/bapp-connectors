"""
FTP storage adapter — implements StoragePort.

This is the main entry point for the FTP integration.
Uses Python's ftplib directly, not ResilientHttpClient.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.ftp.client import FTPClient
from bapp_connectors.providers.storage.ftp.manifest import manifest

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class FTPStorageAdapter(StoragePort):
    """
    FTP storage adapter.

    Implements:
    - StoragePort: upload, download, delete, list_files

    Note: This adapter uses ftplib directly. The http_client parameter is
    accepted for interface compatibility but not used.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, **kwargs):
        self.credentials = credentials

        host = credentials.get("host", "")
        # Derive host from username if not explicitly provided
        if not host and "@" in credentials.get("username", ""):
            host = credentials["username"].split("@")[1]

        self.client = FTPClient(
            host=host,
            port=int(credentials.get("port", 21)),
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
            use_tls=str(credentials.get("use_tls", "false")).lower() == "true",
            timeout=int(credentials.get("timeout", 10)),
            default_folder=credentials.get("default_folder", ""),
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
        """Upload a file to the FTP server. Returns the remote path."""
        self.client.upload_file(file_data, file_name, remote_path)
        target_dir = self.client._with_base(remote_path)
        if target_dir and not target_dir.endswith("/"):
            target_dir += "/"
        return f"{target_dir}{file_name}"

    def download(self, remote_path: str) -> bytes:
        """Download a file from the FTP server. Returns file bytes."""
        return self.client.download_file(remote_path)

    def delete(self, remote_path: str) -> bool:
        """Delete a file from the FTP server. Returns True if successful."""
        try:
            self.client.delete_file(remote_path)
            return True
        except Exception:
            return False

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        """List files in an FTP directory."""
        entries = self.client.list_files(remote_path)
        files = []
        for entry in entries:
            files.append(
                FileInfo(
                    path=entry.get("path", ""),
                    name=entry.get("name", ""),
                    size=entry.get("size", 0),
                    content_type="",
                    modified_at="",
                    is_directory=entry.get("is_directory", False),
                )
            )
        return files
