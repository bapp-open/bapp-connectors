"""Meta provider — one Meta login, Facebook Pages + Instagram accounts as publish destinations."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.meta.adapter import MetaAdapter
from bapp_connectors.providers.social.meta.manifest import manifest

__all__ = ["MetaAdapter", "manifest"]

# Auto-register with the global registry
registry.register(MetaAdapter)
