"""SFTP (SSH File Transfer Protocol) storage provider."""

from bapp_connectors.providers.storage.sftp.adapter import SFTPStorageAdapter
from bapp_connectors.providers.storage.sftp.manifest import manifest

__all__ = ["SFTPStorageAdapter", "manifest"]

# Conditional registration — only if paramiko is installed
try:
    import paramiko  # noqa: F401

    from bapp_connectors.core.registry import registry
    registry.register(SFTPStorageAdapter)
except ImportError:
    pass
