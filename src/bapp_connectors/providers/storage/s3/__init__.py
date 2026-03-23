"""S3-compatible object storage provider (AWS S3, MinIO, DigitalOcean Spaces, etc.)."""

from bapp_connectors.providers.storage.s3.adapter import S3StorageAdapter
from bapp_connectors.providers.storage.s3.manifest import manifest

__all__ = ["S3StorageAdapter", "manifest"]

# Conditional registration — only if boto3 is installed
try:
    import boto3  # noqa: F401

    from bapp_connectors.core.registry import registry
    registry.register(S3StorageAdapter)
except ImportError:
    pass
