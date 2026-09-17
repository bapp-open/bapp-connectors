"""cPanel hosting provider (UAPI)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.hosting.cpanel.adapter import CpanelAdapter
from bapp_connectors.providers.hosting.cpanel.manifest import manifest

__all__ = ["CpanelAdapter", "manifest"]

# Auto-register with the global registry
registry.register(CpanelAdapter)
