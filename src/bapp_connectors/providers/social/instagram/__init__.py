"""Instagram social provider (Instagram Graph API v19.0)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.instagram.adapter import InstagramSocialAdapter
from bapp_connectors.providers.social.instagram.manifest import manifest

__all__ = ["InstagramSocialAdapter", "manifest"]

# Auto-register with the global registry
registry.register(InstagramSocialAdapter)
