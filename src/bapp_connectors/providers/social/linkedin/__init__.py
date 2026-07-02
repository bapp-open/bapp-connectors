"""LinkedIn Page social provider (versioned REST API)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.linkedin.adapter import LinkedInSocialAdapter
from bapp_connectors.providers.social.linkedin.manifest import manifest

__all__ = ["LinkedInSocialAdapter", "manifest"]

# Auto-register with the global registry
registry.register(LinkedInSocialAdapter)
