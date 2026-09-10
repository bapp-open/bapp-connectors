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

from bapp_connectors.providers.storage.errors import FileTooLargeError

logger = logging.getLogger(__name__)

# ftplib's own default is 8192; a larger block means fewer callbacks on a big export
# and a coarser granularity for the byte ceiling, which only has to be approximately
# where it says it is.
DOWNLOAD_BLOCKSIZE = 64 * 1024


def _capped_sink(bio: BytesIO, max_bytes: int):
    """A ``retrbinary`` callback that raises once more than ``max_bytes`` has arrived."""
    total = 0

    def collect(chunk: bytes) -> None:
        nonlocal total
        total += len(chunk)
        if total > max_bytes:
            raise FileTooLargeError(
                f"Download stopped: over the {max_bytes} byte ceiling.",
                max_bytes=max_bytes,
            )
        bio.write(chunk)

    return collect


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

    @contextlib.contextmanager
    def _session(self):
        """An authenticated connection, closed politely on success and abruptly on error.

        ``quit()`` sends QUIT and then waits for the server to answer it. On the error
        path there may be nobody left to answer — a server that timed out, a data
        connection that broke — and that wait burns the whole timeout a second time
        before the real exception surfaces. So a failed operation drops the socket
        instead of saying goodbye.
        """
        connection = self._connect()
        try:
            yield connection
        except BaseException:
            with contextlib.suppress(Exception):
                connection.close()
            raise
        else:
            with contextlib.suppress(Exception):
                connection.quit()

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
            with self._session() as connection:
                connection.voidcmd("NOOP")
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

    def download_file(self, remote_path: str, max_bytes: int | None = None) -> bytes:
        """Download a file from the FTP server.

        The whole file is held in memory. Pass ``max_bytes`` to put a ceiling on that
        and the transfer is abandoned with a `FileTooLargeError` as soon as the bytes
        that have arrived pass it — the check has to happen during the transfer,
        because FTP offers no size before it that is worth the round trips
        (``list_files`` issues a ``CWD`` per entry just to tell files from directories).
        """
        with self._session() as connection:
            target_path = self._with_base(remote_path)
            bio = BytesIO()
            sink = bio.write if max_bytes is None else _capped_sink(bio, max_bytes)
            connection.retrbinary(f"RETR {target_path}", sink, blocksize=DOWNLOAD_BLOCKSIZE)
            return bio.getvalue()

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
