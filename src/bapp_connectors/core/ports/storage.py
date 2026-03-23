"""
Storage port — the common contract for file storage adapters.

Designed to mirror Django's Storage API so adapters can be wrapped as
Django storage backends with minimal effort.

Required methods (abstract):
    save, open, delete, exists, listdir, size

Optional methods (have default implementations that raise NotImplementedError):
    url, path, get_modified_time, get_created_time
"""

from __future__ import annotations

import posixpath
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO

from bapp_connectors.core.ports.base import BasePort


@dataclass
class FileInfo:
    """Metadata about a stored file."""

    path: str
    name: str = ""
    size: int = 0
    content_type: str = ""
    modified_at: str = ""
    is_directory: bool = False
    extra: dict = field(default_factory=dict)


class StoragePort(BasePort):
    """
    Common contract for all file storage adapters (Dropbox, FTP, WebDAV, S3, etc.).

    Method names and signatures follow Django's Storage API:
    https://docs.djangoproject.com/en/5.1/ref/files/storage/
    """

    # ── Required methods (Django Storage core) ──

    @abstractmethod
    def save(self, name: str, content: bytes | IO) -> str:
        """
        Save a file with the given name and content.

        Args:
            name: Full path including filename (e.g., "invoices/2024/inv_001.pdf").
            content: File content as bytes or a file-like object.

        Returns:
            The actual name/path of the saved file.
        """
        ...

    @abstractmethod
    def open(self, name: str) -> IO:
        """
        Open a file and return a file-like object.

        Args:
            name: Full path of the file to open.

        Returns:
            A file-like object (BytesIO) with the file contents.
        """
        ...

    @abstractmethod
    def delete(self, name: str) -> None:
        """
        Delete the file referenced by name.
        Should not raise an error if the file doesn't exist.
        """
        ...

    @abstractmethod
    def exists(self, name: str) -> bool:
        """Return True if the file exists at the given path."""
        ...

    @abstractmethod
    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        """
        List the contents of a directory.

        Returns:
            A tuple of (directories, files) — each a list of names (not full paths).
        """
        ...

    @abstractmethod
    def size(self, name: str) -> int:
        """Return the file size in bytes."""
        ...

    # ── Optional methods (sensible defaults) ──

    def url(self, name: str) -> str:
        """Return a URL where the file can be accessed. Not all backends support this."""
        raise NotImplementedError("This storage backend does not support URL access.")

    def path(self, name: str) -> str:
        """Return a local filesystem path. Only supported by local storage backends."""
        raise NotImplementedError("This storage backend does not support local filesystem paths.")

    def get_modified_time(self, name: str) -> datetime | None:
        """Return the last modified time of the file, or None if not available."""
        return None

    def get_created_time(self, name: str) -> datetime | None:
        """Return the creation time of the file, or None if not available."""
        return None

    # ── Convenience methods (built on top of the abstract ones) ──

    def upload(self, file_data: bytes, file_name: str, remote_path: str = "/") -> str:
        """
        Convenience wrapper: upload a file to a directory.

        This builds the full path from remote_path + file_name, then calls save().
        Kept for backward compatibility with existing code that uses upload().
        """
        full_path = posixpath.join(remote_path.rstrip("/"), file_name) if remote_path else file_name
        return self.save(full_path, file_data)

    def download(self, remote_path: str) -> bytes:
        """
        Convenience wrapper: download a file and return bytes.

        Calls open() and reads the content.
        """
        f = self.open(remote_path)
        try:
            return f.read()
        finally:
            f.close()

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        """
        Convenience wrapper: list files as FileInfo objects.

        Calls listdir() and converts to FileInfo. Adapters can override
        for richer metadata.
        """
        dirs, files = self.listdir(remote_path)
        result = []
        for d in dirs:
            result.append(FileInfo(
                path=posixpath.join(remote_path, d),
                name=d,
                is_directory=True,
            ))
        for f in files:
            full_path = posixpath.join(remote_path, f)
            result.append(FileInfo(
                path=full_path,
                name=f,
                is_directory=False,
            ))
        return result
