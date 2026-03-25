"""Google Drive storage provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.storage.google_drive.adapter import GoogleDriveStorageAdapter
from bapp_connectors.providers.storage.google_drive.manifest import manifest

__all__ = ["GoogleDriveStorageAdapter", "manifest"]

registry.register(GoogleDriveStorageAdapter)
