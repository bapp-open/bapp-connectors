"""
SFTP storage adapter — implements StoragePort.

Provides encrypted file access to remote servers over SSH.
Requires the `paramiko` package (pip install paramiko).
"""

from __future__ import annotations

import posixpath
from datetime import UTC, datetime
from io import BytesIO
from typing import IO, TYPE_CHECKING

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.sftp.client import SFTPClient
from bapp_connectors.providers.storage.sftp.manifest import manifest

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class SFTPStorageAdapter(StoragePort):
    """
    SFTP storage adapter.

    Implements:
    - StoragePort: save, open, delete, exists, listdir, size, list_files

    Note: This adapter uses paramiko (SSH) directly. The http_client parameter
    is accepted for interface compatibility but not used.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self.client = SFTPClient(
            host=credentials.get("host", ""),
            port=config.get("port", 22),
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
            private_key=credentials.get("private_key", ""),
            default_folder=config.get("default_folder", "/"),
            timeout=config.get("timeout", 10),
            verify_host_key=config.get("verify_host_key", False),
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        creds = self.credentials
        if not creds.get("host") or not creds.get("username"):
            return False
        if not creds.get("password") and not creds.get("private_key"):
            return False
        return True

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="SFTP connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── StoragePort (Django Storage API) ──

    def save(self, name: str, content: bytes | IO) -> str:
        if isinstance(content, bytes):
            data = content
        else:
            data = content.read()
        directory = posixpath.dirname(name) or "/"
        file_name = posixpath.basename(name)
        self.client.upload(data, file_name, directory)
        return name

    def open(self, name: str) -> IO:
        data = self.client.download(name)
        return BytesIO(data)

    def delete(self, name: str) -> None:
        try:
            self.client.delete(name)
        except Exception:
            pass

    def exists(self, name: str) -> bool:
        return self.client.exists(name)

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        entries = self.client.list_directory(path)
        dirs = [e["name"] for e in entries if e.get("is_directory")]
        files = [e["name"] for e in entries if not e.get("is_directory")]
        return dirs, files

    def size(self, name: str) -> int:
        try:
            info = self.client.stat(name)
            return info.get("size", 0)
        except Exception:
            return 0

    def get_modified_time(self, name: str) -> datetime | None:
        try:
            info = self.client.stat(name)
            mtime = info.get("modified_at", 0)
            if mtime:
                return datetime.fromtimestamp(mtime, tz=UTC)
        except Exception:
            pass
        return None

    # ── Convenience override with richer metadata ──

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        entries = self.client.list_directory(remote_path)
        return [
            FileInfo(
                path=entry["path"],
                name=entry["name"],
                size=entry["size"],
                modified_at=str(entry["modified_at"]),
                is_directory=entry["is_directory"],
            )
            for entry in entries
        ]
