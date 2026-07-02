"""YouTube Shorts social provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.youtube.adapter import YouTubeSocialAdapter
from bapp_connectors.providers.social.youtube.manifest import manifest

__all__ = ["YouTubeSocialAdapter", "manifest"]

# Auto-register with the global registry
registry.register(YouTubeSocialAdapter)
