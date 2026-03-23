"""
FTP storage client — uses Python's ftplib directly (not ResilientHttpClient).

Handles FTP connection management and file operations.
"""

from __future__ import annotations

import contextlib
import logging
from ftplib import FTP, FTP_TLS, error_perm
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)


class FTPClient:
    """
    Low-level FTP client.

    This class handles FTP connection and file operations.
    A new connection is created for each operation to avoid stale connections.
    """

    def __init__(
        self,
        host: str,
        port: int = 21,
        username: str = "",
        password: str = "",
        use_tls: bool = False,
        timeout: int = 10,
        default_folder: str = "",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout = timeout
        self.default_folder = self._normalize_path(default_folder) if default_folder.strip() else ""

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize to an FTP path that starts with '/' and has no trailing slash."""
        if not path:
            return ""
        path = "/" + path.strip().lstrip("/")
        if path != "/":
            path = path.rstrip("/")
        return path

    def _with_base(self, path: str) -> str:
        """Apply default_folder to relative paths only."""
        path = path or ""
        if path.startswith("/"):
            return self._normalize_path(path)

        base = (self.default_folder or "").strip()
        if not base:
            return self._normalize_path(path)

        base = "/" + base.strip("/")
        if not path or path.strip() in (".", "/"):
            return self._normalize_path(base)
        return self._normalize_path(str(PurePosixPath(base) / path))

    def _connect(self) -> FTP | FTP_TLS:
        """Create and authenticate an FTP connection."""
        connection = FTP_TLS(timeout=self.timeout) if self.use_tls else FTP(timeout=self.timeout)

        connection.connect(host=self.host, port=self.port)
        connection.login(user=self.username, passwd=self.password)

        if self.use_tls and isinstance(connection, FTP_TLS):
            connection.prot_p()

        return connection

    def _ensure_directory(self, connection: FTP, path: str) -> None:
        """Ensure that the directory path exists, creating it if needed."""
        if not path or path == "/":
            return

        current_dir = ""
        for directory in path.strip("/").split("/"):
            if not directory:
                continue
            current_dir += f"/{directory}"
            try:
                connection.cwd(current_dir)
            except error_perm:
                with contextlib.suppress(error_perm):
                    connection.mkd(current_dir)
                connection.cwd(current_dir)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Test FTP authentication by connecting and sending NOOP."""
        try:
            connection = self._connect()
            connection.voidcmd("NOOP")
            connection.quit()
            return True
        except Exception:
            return False

    # ── File Operations ──

    def upload_file(self, file_data: bytes, file_name: str, remote_path: str) -> None:
        """Upload a file to the FTP server."""
        connection = self._connect()
        try:
            target_dir = self._with_base(remote_path)
            self._ensure_directory(connection, target_dir)
            connection.cwd(target_dir)
            bio = BytesIO(file_data)
            connection.storbinary(f"STOR {file_name}", bio)
            bio.close()
        finally:
            with contextlib.suppress(Exception):
                connection.quit()

    def download_file(self, remote_path: str) -> bytes:
        """Download a file from the FTP server."""
        connection = self._connect()
        try:
            target_path = self._with_base(remote_path)
            bio = BytesIO()
            connection.retrbinary(f"RETR {target_path}", bio.write)
            return bio.getvalue()
        finally:
            with contextlib.suppress(Exception):
                connection.quit()

    def delete_file(self, remote_path: str) -> None:
        """Delete a file from the FTP server."""
        connection = self._connect()
        try:
            target_path = self._with_base(remote_path)
            connection.delete(target_path)
        finally:
            with contextlib.suppress(Exception):
                connection.quit()

    def list_files(self, remote_path: str = "/") -> list[dict[str, Any]]:
        """
        List files in an FTP directory.

        Returns a list of dicts with 'name' and 'is_directory' keys.
        """
        connection = self._connect()
        try:
            target_path = self._with_base(remote_path) or "/"
            items = connection.nlst(target_path)

            results: list[dict[str, Any]] = []
            for item in items:
                basename = PurePosixPath(item.rstrip("/")).name
                if basename in (".", "..", ""):
                    continue

                # Try to determine if it's a directory
                is_dir = False
                try:
                    connection.cwd(item)
                    is_dir = True
                    connection.cwd(target_path)
                except error_perm:
                    pass

                # Try to get file size
                size = 0
                if not is_dir:
                    with contextlib.suppress(Exception):
                        size = connection.size(item) or 0

                results.append(
                    {
                        "path": item,
                        "name": basename,
                        "size": size,
                        "is_directory": is_dir,
                    }
                )

            return results
        finally:
            with contextlib.suppress(Exception):
                connection.quit()
