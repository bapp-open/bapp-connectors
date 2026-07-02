"""Threads social provider (Threads API, graph.threads.net v1.0)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.threads.adapter import ThreadsSocialAdapter
from bapp_connectors.providers.social.threads.manifest import manifest

__all__ = ["ThreadsSocialAdapter", "manifest"]

# Auto-register with the global registry
registry.register(ThreadsSocialAdapter)
