"""FTP file storage provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.storage.ftp.adapter import FTPStorageAdapter
from bapp_connectors.providers.storage.ftp.manifest import manifest

__all__ = ["FTPStorageAdapter", "manifest"]

# Auto-register with the global registry
registry.register(FTPStorageAdapter)
