"""
S3-compatible storage client — uses boto3 for all S3 operations.

Works with AWS S3 and any S3-compatible service (MinIO, DigitalOcean Spaces,
Backblaze B2, Cloudflare R2) via the endpoint_url parameter.

Does NOT use ResilientHttpClient — boto3 handles auth (SigV4), retries, and
connection pooling internally.
"""

from __future__ import annotations

import logging
import posixpath
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None  # type: ignore[assignment]
    BotoConfig = None  # type: ignore[assignment, misc]
    ClientError = Exception  # type: ignore[assignment, misc]


def _require_boto3():
    if boto3 is None:
        raise ImportError(
            "boto3 is required for S3 storage. "
            "Install it with: pip install boto3"
        )


class S3Client:
    """
    Low-level S3-compatible storage client using boto3.

    Handles: upload, download, delete, exists, stat, list, head_bucket.
    """

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str = "",
        default_prefix: str = "",
        addressing_style: str = "auto",
    ):
        _require_boto3()
        self.bucket = bucket
        self.default_prefix = default_prefix.strip("/")

        config = BotoConfig(
            s3={"addressing_style": addressing_style},
            retries={"max_attempts": 3, "mode": "standard"},
        )

        session = boto3.session.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

        kwargs: dict[str, Any] = {"config": config}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url

        self.s3 = session.client("s3", **kwargs)

    def _key(self, path: str) -> str:
        """Build full S3 key from a path, applying default_prefix."""
        path = path.lstrip("/")
        if self.default_prefix:
            return f"{self.default_prefix}/{path}" if path else self.default_prefix
        return path

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by calling HeadBucket."""
        try:
            self.s3.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False

    # ── Upload ──

    def upload(self, file_data: bytes, key: str, content_type: str = "") -> None:
        """PutObject — upload bytes to a key."""
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": self._key(key), "Body": file_data}
        if content_type:
            kwargs["ContentType"] = content_type
        self.s3.put_object(**kwargs)

    # ── Download ──

    def download(self, key: str) -> bytes:
        """GetObject — download a key and return bytes."""
        response = self.s3.get_object(Bucket=self.bucket, Key=self._key(key))
        return response["Body"].read()

    # ── Delete ──

    def delete(self, key: str) -> None:
        """DeleteObject — delete a key. Does not raise if key doesn't exist."""
        self.s3.delete_object(Bucket=self.bucket, Key=self._key(key))

    # ── Exists ──

    def exists(self, key: str) -> bool:
        """HeadObject — check if a key exists."""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    # ── Metadata ──

    def stat(self, key: str) -> dict[str, Any]:
        """HeadObject — return size, content_type, last_modified."""
        response = self.s3.head_object(Bucket=self.bucket, Key=self._key(key))
        return {
            "size": response.get("ContentLength", 0),
            "content_type": response.get("ContentType", ""),
            "last_modified": response.get("LastModified"),
            "etag": response.get("ETag", ""),
        }

    # ── List ──

    def list_objects(self, prefix: str = "", delimiter: str = "/") -> dict[str, Any]:
        """
        ListObjectsV2 — list objects under a prefix.

        Returns dict with keys:
            - objects: list of {key, size, last_modified}
            - prefixes: list of common prefix strings (subdirectories)
            - is_truncated: bool
            - next_token: str or None
        """
        full_prefix = self._key(prefix)
        if full_prefix and not full_prefix.endswith("/"):
            full_prefix += "/"

        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Prefix": full_prefix,
            "Delimiter": delimiter,
            "MaxKeys": 1000,
        }

        response = self.s3.list_objects_v2(**kwargs)

        objects = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            # Skip the prefix itself
            if key == full_prefix:
                continue
            objects.append({
                "key": key,
                "name": posixpath.basename(key.rstrip("/")),
                "size": obj.get("Size", 0),
                "last_modified": obj.get("LastModified"),
            })

        prefixes = []
        for cp in response.get("CommonPrefixes", []):
            p = cp.get("Prefix", "")
            name = p.rstrip("/").rsplit("/", 1)[-1] if "/" in p else p.rstrip("/")
            if name:
                prefixes.append(name)

        return {
            "objects": objects,
            "prefixes": prefixes,
            "is_truncated": response.get("IsTruncated", False),
            "next_token": response.get("NextContinuationToken"),
        }
