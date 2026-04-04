"""SMTP email provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter
from bapp_connectors.providers.email.smtp.manifest import manifest

__all__ = ["SMTPEmailAdapter", "manifest"]

# Auto-register with the global registry
registry.register(SMTPEmailAdapter)
