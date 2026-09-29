"""Cargus courier provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.cargus.adapter import CargusCourierAdapter
from bapp_connectors.providers.courier.cargus.manifest import manifest

__all__ = ["CargusCourierAdapter", "manifest"]

# Auto-register with the global registry
registry.register(CargusCourierAdapter)
