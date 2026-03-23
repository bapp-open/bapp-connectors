"""Dropbox file storage provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.storage.dropbox.adapter import DropboxStorageAdapter
from bapp_connectors.providers.storage.dropbox.manifest import manifest

__all__ = ["DropboxStorageAdapter", "manifest"]

# Auto-register with the global registry
registry.register(DropboxStorageAdapter)
