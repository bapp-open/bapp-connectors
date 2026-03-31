"""Matrix messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.matrix.adapter import MatrixMessagingAdapter
from bapp_connectors.providers.messaging.matrix.manifest import manifest

__all__ = ["MatrixMessagingAdapter", "manifest"]

registry.register(MatrixMessagingAdapter)
