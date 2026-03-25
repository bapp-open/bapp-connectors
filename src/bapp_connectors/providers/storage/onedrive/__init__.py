"""OneDrive storage provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.storage.onedrive.adapter import OneDriveStorageAdapter
from bapp_connectors.providers.storage.onedrive.manifest import manifest

__all__ = ["OneDriveStorageAdapter", "manifest"]

registry.register(OneDriveStorageAdapter)
