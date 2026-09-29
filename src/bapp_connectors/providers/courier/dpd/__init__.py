"""DPD Romania courier provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.dpd.adapter import DpdCourierAdapter
from bapp_connectors.providers.courier.dpd.manifest import manifest

__all__ = ["DpdCourierAdapter", "manifest"]

# Auto-register with the global registry
registry.register(DpdCourierAdapter)
