"""Pinterest social provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.pinterest.adapter import PinterestSocialAdapter
from bapp_connectors.providers.social.pinterest.manifest import manifest

__all__ = ["PinterestSocialAdapter", "manifest"]

# Auto-register with the global registry
registry.register(PinterestSocialAdapter)
