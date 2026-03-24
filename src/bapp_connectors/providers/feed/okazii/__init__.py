"""Okazii.ro feed provider."""

from bapp_connectors.core.registry import registry

from .adapter import OkaziiFeedAdapter

registry.register(OkaziiFeedAdapter)
