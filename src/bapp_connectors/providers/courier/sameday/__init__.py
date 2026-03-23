"""Sameday courier provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.sameday.adapter import SamedayCourierAdapter
from bapp_connectors.providers.courier.sameday.manifest import manifest

__all__ = ["SamedayCourierAdapter", "manifest"]

# Auto-register with the global registry
registry.register(SamedayCourierAdapter)
