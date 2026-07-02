"""TikTok Ads provider (TikTok Business API v1.3)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.ads.tiktok.adapter import TikTokAdsAdapter
from bapp_connectors.providers.ads.tiktok.manifest import manifest

__all__ = ["TikTokAdsAdapter", "manifest"]

# Auto-register with the global registry
registry.register(TikTokAdsAdapter)
