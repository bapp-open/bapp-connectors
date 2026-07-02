"""Facebook Page social provider (Graph API v19.0)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.facebook.adapter import FacebookSocialAdapter
from bapp_connectors.providers.social.facebook.manifest import manifest

__all__ = ["FacebookSocialAdapter", "manifest"]

# Auto-register with the global registry
registry.register(FacebookSocialAdapter)
