"""GLS courier provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.gls.adapter import GLSCourierAdapter
from bapp_connectors.providers.courier.gls.manifest import manifest

__all__ = ["GLSCourierAdapter", "manifest"]

# Auto-register with the global registry
registry.register(GLSCourierAdapter)
