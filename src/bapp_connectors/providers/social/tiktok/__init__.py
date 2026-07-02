"""TikTok Display API social provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.social.tiktok.adapter import TikTokSocialAdapter
from bapp_connectors.providers.social.tiktok.manifest import manifest

__all__ = ["TikTokSocialAdapter", "manifest"]

# Auto-register with the global registry
registry.register(TikTokSocialAdapter)
