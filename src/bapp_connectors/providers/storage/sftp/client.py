"""
SFTP storage client — uses paramiko for SSH/SFTP operations.

Handles connection management, file operations, and directory traversal.
Each operation opens a fresh connection by default. Use connect() as a
context manager for batch operations to reuse a single connection.
"""

from __future__ import annotations

import contextlib
import logging
import posixpath
import stat
from io import BytesIO, StringIO
from typing import Any

logger = logging.getLogger(__name__)

try:
    import paramiko
except ImportError:
    paramiko = None  # type: ignore[assignment]


def _require_paramiko():
    if paramiko is None:
        raise ImportError(
            "paramiko is required for SFTP storage. "
            "Install it with: pip install paramiko"
        )


class SFTPClient:
    """
    Low-level SFTP client using paramiko.

    Each public method opens and closes its own SSH connection.
    For batch operations, use the connect() context manager.
    """

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "",
        password: str = "",
        private_key: str = "",
        default_folder: str = "/",
        timeout: int = 10,
        verify_host_key: bool = False,
    ):
        _require_paramiko()
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.default_folder = default_folder.strip() or "/"
        self.timeout = timeout
        self.verify_host_key = verify_host_key

    def _get_pkey(self) -> paramiko.PKey | None:
        """Parse the private key string into a paramiko PKey."""
        if not self.private_key:
            return None
        key_str = self.private_key.strip()
        key_file = StringIO(key_str)
        # Try RSA, then Ed25519, then ECDSA
        for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                key_file.seek(0)
                return key_class.from_private_key(key_file)
            except Exception:
                continue
        raise ValueError("Could not parse SSH private key. Supported types: RSA, Ed25519, ECDSA.")

    def _connect_transport(self) -> paramiko.Transport:
        """Create an authenticated SSH transport."""
        transport = paramiko.Transport((self.host, self.port))
        transport.connect(
            username=self.username,
            password=self.password or None,
            pkey=self._get_pkey(),
        )
        return transport

    def _open_sftp(self) -> tuple[paramiko.Transport, paramiko.SFTPClient]:
        """Open an SFTP session. Returns (transport, sftp) — caller must close both."""
        transport = self._connect_transport()
        sftp = paramiko.SFTPClient.from_transport(transport)
        return transport, sftp

    @contextlib.contextmanager
    def connect(self):
        """
        Context manager for batch operations over a single connection.

        Usage:
            with client.connect() as sftp:
                sftp.upload(...)
                sftp.download(...)
        """
        transport, sftp = self._open_sftp()
        try:
            yield _SFTPSession(sftp, self)
        finally:
            sftp.close()
            transport.close()

    def _with_base(self, path: str) -> str:
        """Prefix relative paths with the default folder."""
        if not path:
            return self.default_folder
        if path.startswith("/"):
            return path
        return posixpath.join(self.default_folder.rstrip("/"), path)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify SSH credentials by connecting and listing the root."""
        try:
            transport, sftp = self._open_sftp()
            try:
                sftp.listdir(self.default_folder)
                return True
            finally:
                sftp.close()
                transport.close()
        except Exception:
            return False

    # ── File Operations ──

    def upload(self, file_data: bytes, file_name: str, remote_path: str) -> None:
        """Upload a file, creating intermediate directories."""
        transport, sftp = self._open_sftp()
        try:
            target_dir = self._with_base(remote_path)
            _ensure_directory(sftp, target_dir)
            full_path = posixpath.join(target_dir, file_name)
            with sftp.open(full_path, "wb") as f:
                f.write(file_data)
        finally:
            sftp.close()
            transport.close()

    def download(self, remote_path: str) -> bytes:
        """Download a file and return its contents as bytes."""
        transport, sftp = self._open_sftp()
        try:
            target = self._with_base(remote_path)
            buf = BytesIO()
            sftp.getfo(target, buf)
            return buf.getvalue()
        finally:
            sftp.close()
            transport.close()

    def delete(self, remote_path: str) -> None:
        """Delete a file."""
        transport, sftp = self._open_sftp()
        try:
            target = self._with_base(remote_path)
            sftp.remove(target)
        finally:
            sftp.close()
            transport.close()

    def exists(self, remote_path: str) -> bool:
        """Check if a file or directory exists."""
        transport, sftp = self._open_sftp()
        try:
            target = self._with_base(remote_path)
            try:
                sftp.stat(target)
                return True
            except FileNotFoundError:
                return False
        finally:
            sftp.close()
            transport.close()

    def stat(self, remote_path: str) -> dict[str, Any]:
        """Get file metadata (size, modified time, is_directory)."""
        transport, sftp = self._open_sftp()
        try:
            target = self._with_base(remote_path)
            attrs = sftp.stat(target)
            return {
                "size": attrs.st_size or 0,
                "modified_at": attrs.st_mtime or 0,
                "is_directory": stat.S_ISDIR(attrs.st_mode) if attrs.st_mode else False,
            }
        finally:
            sftp.close()
            transport.close()

    def list_directory(self, remote_path: str) -> list[dict[str, Any]]:
        """List directory contents with metadata."""
        transport, sftp = self._open_sftp()
        try:
            target = self._with_base(remote_path)
            entries = sftp.listdir_attr(target)
            results = []
            for entry in entries:
                name = entry.filename
                if name in (".", ".."):
                    continue
                is_dir = stat.S_ISDIR(entry.st_mode) if entry.st_mode else False
                results.append({
                    "path": posixpath.join(target, name),
                    "name": name,
                    "size": entry.st_size or 0,
                    "modified_at": entry.st_mtime or 0,
                    "is_directory": is_dir,
                })
            return results
        finally:
            sftp.close()
            transport.close()


class _SFTPSession:
    """Wrapper around an open SFTP session for batch operations."""

    def __init__(self, sftp: paramiko.SFTPClient, client: SFTPClient):
        self._sftp = sftp
        self._client = client

    def upload(self, file_data: bytes, file_name: str, remote_path: str) -> None:
        target_dir = self._client._with_base(remote_path)
        _ensure_directory(self._sftp, target_dir)
        full_path = posixpath.join(target_dir, file_name)
        with self._sftp.open(full_path, "wb") as f:
            f.write(file_data)

    def download(self, remote_path: str) -> bytes:
        target = self._client._with_base(remote_path)
        buf = BytesIO()
        self._sftp.getfo(target, buf)
        return buf.getvalue()

    def delete(self, remote_path: str) -> None:
        target = self._client._with_base(remote_path)
        self._sftp.remove(target)

    def exists(self, remote_path: str) -> bool:
        target = self._client._with_base(remote_path)
        try:
            self._sftp.stat(target)
            return True
        except FileNotFoundError:
            return False


def _ensure_directory(sftp: paramiko.SFTPClient, path: str) -> None:
    """Recursively create directories via SFTP."""
    if not path or path == "/":
        return
    parts = [p for p in path.split("/") if p]
    current = "/"
    for part in parts:
        current = posixpath.join(current, part)
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)
