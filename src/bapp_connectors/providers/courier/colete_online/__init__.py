"""Colete Online courier provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.colete_online.adapter import ColeteOnlineCourierAdapter
from bapp_connectors.providers.courier.colete_online.manifest import manifest

__all__ = ["ColeteOnlineCourierAdapter", "manifest"]

# Auto-register with the global registry
registry.register(ColeteOnlineCourierAdapter)
