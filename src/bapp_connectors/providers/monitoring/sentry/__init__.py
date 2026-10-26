"""Sentry monitoring provider (REST API v0)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.monitoring.sentry.adapter import SentryAdapter
from bapp_connectors.providers.monitoring.sentry.manifest import manifest

__all__ = ["SentryAdapter", "manifest"]

# Auto-register with the global registry
registry.register(SentryAdapter)
