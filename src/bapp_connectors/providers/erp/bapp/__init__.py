"""BAPP ERP provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.erp.bapp.adapter import BappErpAdapter
from bapp_connectors.providers.erp.bapp.manifest import manifest

__all__ = ["BappErpAdapter", "manifest"]

# Auto-register with the global registry
registry.register(BappErpAdapter)
