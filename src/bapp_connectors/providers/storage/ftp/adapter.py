"""
FTP storage adapter — implements StoragePort.

This is the main entry point for the FTP integration.
Uses Python's ftplib directly, not ResilientHttpClient.
"""

from __future__ import annotations

import posixpath
from io import BytesIO
from typing import IO, TYPE_CHECKING

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
    - StoragePort: save, open, delete, exists, listdir, size, list_files

    Note: This adapter uses ftplib directly. The http_client parameter is
    accepted for interface compatibility but not used.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials

        host = credentials.get("host", "")
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

    # ── StoragePort (Django Storage API) ──

    def save(self, name: str, content: bytes | IO) -> str:
        if isinstance(content, bytes):
            data = content
        else:
            data = content.read()
        directory = posixpath.dirname(name) or "/"
        file_name = posixpath.basename(name)
        self.client.upload_file(data, file_name, directory)
        target_dir = self.client._with_base(directory)
        if target_dir and not target_dir.endswith("/"):
            target_dir += "/"
        return f"{target_dir}{file_name}"

    def open(self, name: str) -> IO:
        data = self.client.download_file(name)
        return BytesIO(data)

    def delete(self, name: str) -> None:
        try:
            self.client.delete_file(name)
        except Exception:
            pass

    def exists(self, name: str) -> bool:
        try:
            conn = self.client._connect()
            try:
                target = self.client._with_base(name)
                # Try SIZE (works for files)
                conn.size(target)
                return True
            except Exception:
                # Try CWD (works for directories)
                try:
                    conn.cwd(target)
                    return True
                except Exception:
                    return False
            finally:
                try:
                    conn.quit()
                except Exception:
                    pass
        except Exception:
            return False

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        entries = self.client.list_files(path)
        dirs = [e["name"] for e in entries if e.get("is_directory")]
        files = [e["name"] for e in entries if not e.get("is_directory")]
        return dirs, files

    def size(self, name: str) -> int:
        try:
            conn = self.client._connect()
            try:
                target = self.client._with_base(name)
                return conn.size(target) or 0
            finally:
                try:
                    conn.quit()
                except Exception:
                    pass
        except Exception:
            return 0

    # ── Convenience override with richer metadata ──

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        entries = self.client.list_files(remote_path)
        return [
            FileInfo(
                path=entry.get("path", ""),
                name=entry.get("name", ""),
                size=entry.get("size", 0),
                is_directory=entry.get("is_directory", False),
            )
            for entry in entries
        ]
