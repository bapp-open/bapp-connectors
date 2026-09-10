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
import socket
import stat
from io import BytesIO, StringIO
from typing import Any

from bapp_connectors.providers.storage.errors import FileTooLargeError

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
        """
        ``timeout`` bounds the TCP connect, the SSH banner and the authentication.

        ``verify_host_key`` is accepted for API compatibility and **not honoured** —
        every connection trusts the key the server presents. Honouring it needs a
        ``known_hosts`` the caller can point at, which no caller has yet; until one
        does, the flag stays out of the manifest so it is not offered as a setting
        that does nothing.
        """
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
        """Create an authenticated SSH transport, every phase bounded by ``self.timeout``.

        The socket is opened here rather than left to paramiko. Handed a
        ``(host, port)`` tuple, ``paramiko.Transport`` builds a bare socket and calls
        ``sock.connect()`` with no timeout at all, so a host that swallows packets
        holds the caller for as long as the operating system's TCP timeout — minutes,
        on a default Linux. Giving ``Transport`` a socket that is already connected is
        the supported way to bound that.

        The connect is all that socket buys us: paramiko replaces the timeout with its
        own 0.1s poll interval the moment it takes the socket over, so the banner and
        authentication phases need bounds of their own.
        """
        # Parsed before the socket is opened: a malformed key is the caller's mistake,
        # and there is no reason to reach the server to find that out.
        pkey = self._get_pkey()

        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        try:
            transport = paramiko.Transport(sock)
        except Exception:
            sock.close()
            raise

        transport.banner_timeout = self.timeout
        transport.auth_timeout = self.timeout
        try:
            transport.connect(
                username=self.username,
                password=self.password or None,
                pkey=pkey,
            )
        except Exception:
            transport.close()
            raise
        return transport

    def _open_sftp(self) -> tuple[paramiko.Transport, paramiko.SFTPClient]:
        """Open an SFTP session. Returns (transport, sftp) — caller must close both."""
        transport = self._connect_transport()
        try:
            sftp = paramiko.SFTPClient.from_transport(transport)
        except Exception:
            transport.close()
            raise
        if sftp is None:
            # from_transport returns None when the server refuses the sftp subsystem.
            transport.close()
            raise paramiko.SSHException(f"Could not open an SFTP session on {self.host}.")
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

    def download(self, remote_path: str, max_bytes: int | None = None) -> bytes:
        """Download a file and return its contents as bytes.

        The whole file is held in memory. Pass ``max_bytes`` to put a ceiling on that:
        the size is read from a ``stat`` first, so a file that is already too big costs
        one round trip instead of a transfer, and the ceiling is enforced again on the
        bytes as they arrive. Either way the refusal is a `FileTooLargeError`.
        """
        transport, sftp = self._open_sftp()
        try:
            return _download(sftp, self._with_base(remote_path), max_bytes)
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

    def download(self, remote_path: str, max_bytes: int | None = None) -> bytes:
        target = self._client._with_base(remote_path)
        return _download(self._sftp, target, max_bytes)

    def stat(self, remote_path: str) -> dict[str, Any]:
        """Same shape as ``SFTPClient.stat`` — size, mtime, is_directory.

        On the session so that a size check and the download it guards can share one
        SSH handshake instead of paying for two.
        """
        target = self._client._with_base(remote_path)
        attrs = self._sftp.stat(target)
        return {
            "size": attrs.st_size or 0,
            "modified_at": attrs.st_mtime or 0,
            "is_directory": stat.S_ISDIR(attrs.st_mode) if attrs.st_mode else False,
        }

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


class _CappedWriter:
    """A sink for ``getfo`` that refuses to hold more than ``max_bytes``.

    Catches the two cases a ``stat`` beforehand cannot: a file that grows between the
    stat and the read, and a server that misreports the size.
    """

    def __init__(self, max_bytes: int):
        self._max_bytes = max_bytes
        self._buffer = BytesIO()
        self.total = 0

    def write(self, data: bytes) -> int:
        self.total += len(data)
        if self.total > self._max_bytes:
            raise FileTooLargeError(
                f"Download stopped: over the {self._max_bytes} byte ceiling.",
                max_bytes=self._max_bytes,
            )
        return self._buffer.write(data)

    def getvalue(self) -> bytes:
        return self._buffer.getvalue()


def _download(sftp: paramiko.SFTPClient, target: str, max_bytes: int | None) -> bytes:
    """Read ``target`` into memory, refusing anything over ``max_bytes``."""
    if max_bytes is None:
        buf = BytesIO()
        sftp.getfo(target, buf)
        return buf.getvalue()

    size = sftp.stat(target).st_size or 0
    if size > max_bytes:
        raise FileTooLargeError(
            f"File is {size} bytes, over the {max_bytes} byte ceiling.",
            max_bytes=max_bytes,
            size=size,
        )
    sink = _CappedWriter(max_bytes)
    sftp.getfo(target, sink)
    return sink.getvalue()


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
