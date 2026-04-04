"""Gmail email provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.email.gmail.adapter import GmailEmailAdapter
from bapp_connectors.providers.email.gmail.manifest import manifest

__all__ = ["GmailEmailAdapter", "manifest"]

# Auto-register with the global registry
registry.register(GmailEmailAdapter)
