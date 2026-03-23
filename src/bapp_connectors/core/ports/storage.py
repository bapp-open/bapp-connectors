"""
Storage port — the common contract for file storage adapters.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

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


class StoragePort(BasePort):
    """
    Common contract for all file storage adapters (Dropbox, FTP, S3, etc.).
    """

    @abstractmethod
    def upload(self, file_data: bytes, file_name: str, remote_path: str) -> str:
        """Upload a file. Returns the remote path or URL."""
        ...

    @abstractmethod
    def download(self, remote_path: str) -> bytes:
        """Download a file. Returns file bytes."""
        ...

    @abstractmethod
    def delete(self, remote_path: str) -> bool:
        """Delete a file. Returns True if successful."""
        ...

    @abstractmethod
    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        """List files in a directory."""
        ...
