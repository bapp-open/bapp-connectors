"""SAGA Web accounting provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.accounting.saga_web.adapter import SagaWebAdapter
from bapp_connectors.providers.accounting.saga_web.manifest import manifest

__all__ = ["SagaWebAdapter", "manifest"]

# Auto-register with the global registry
registry.register(SagaWebAdapter)
