"""
S3-compatible storage adapter — implements StoragePort.

Works with AWS S3, MinIO, DigitalOcean Spaces, Backblaze B2, Cloudflare R2,
and any S3-compatible service.

Requires the `boto3` package (pip install boto3).
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import IO, TYPE_CHECKING

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.s3.client import S3Client
from bapp_connectors.providers.storage.s3.manifest import manifest

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class S3StorageAdapter(StoragePort):
    """
    S3-compatible object storage adapter.

    Implements:
    - StoragePort: save, open, delete, exists, listdir, size, url, list_files

    Note: This adapter uses boto3 directly. The http_client parameter is
    accepted for interface compatibility but not used.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._bucket = credentials.get("bucket", "")
        self._endpoint_url = config.get("endpoint_url", "")

        self.client = S3Client(
            access_key_id=credentials.get("access_key_id", ""),
            secret_access_key=credentials.get("secret_access_key", ""),
            bucket=self._bucket,
            region=config.get("region", "us-east-1"),
            endpoint_url=self._endpoint_url,
            default_prefix=config.get("default_prefix", ""),
            addressing_style=config.get("addressing_style", "auto"),
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
                message=f"Connected to bucket '{self._bucket}'" if success else "Authentication or bucket access failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── StoragePort (Django Storage API) ──

    def save(self, name: str, content: bytes | IO) -> str:
        if isinstance(content, bytes):
            data = content
        else:
            data = content.read()
        self.client.upload(data, name)
        return name

    def open(self, name: str) -> IO:
        data = self.client.download(name)
        return BytesIO(data)

    def delete(self, name: str) -> None:
        self.client.delete(name)

    def exists(self, name: str) -> bool:
        return self.client.exists(name)

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        result = self.client.list_objects(prefix=path)
        dirs = result["prefixes"]
        files = [obj["name"] for obj in result["objects"]]
        return dirs, files

    def size(self, name: str) -> int:
        try:
            info = self.client.stat(name)
            return info.get("size", 0)
        except Exception:
            return 0

    def url(self, name: str) -> str:
        """Generate an unsigned URL for the object."""
        key = self.client._key(name)
        if self._endpoint_url:
            base = self._endpoint_url.rstrip("/")
            return f"{base}/{self._bucket}/{key}"
        return f"https://{self._bucket}.s3.amazonaws.com/{key}"

    def get_modified_time(self, name: str) -> datetime | None:
        try:
            info = self.client.stat(name)
            return info.get("last_modified")
        except Exception:
            return None

    # ── Convenience override with richer metadata ──

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        result = self.client.list_objects(prefix=remote_path)
        files = []
        for prefix in result["prefixes"]:
            files.append(FileInfo(
                path=prefix,
                name=prefix,
                is_directory=True,
            ))
        for obj in result["objects"]:
            files.append(FileInfo(
                path=obj["key"],
                name=obj["name"],
                size=obj["size"],
                modified_at=str(obj.get("last_modified", "")),
                is_directory=False,
            ))
        return files
