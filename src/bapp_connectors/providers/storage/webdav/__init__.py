"""WebDAV file storage provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.storage.webdav.adapter import WebDAVStorageAdapter
from bapp_connectors.providers.storage.webdav.manifest import manifest

__all__ = ["WebDAVStorageAdapter", "manifest"]

# Auto-register with the global registry
registry.register(WebDAVStorageAdapter)
