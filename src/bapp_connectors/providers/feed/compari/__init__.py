"""Compari.ro feed provider."""

from bapp_connectors.core.registry import registry

from .adapter import CompariFeedAdapter

registry.register(CompariFeedAdapter)
