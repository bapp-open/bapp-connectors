"""Pinterest Ads provider (Pinterest API v5)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.ads.pinterest.adapter import PinterestAdsAdapter
from bapp_connectors.providers.ads.pinterest.manifest import manifest

__all__ = ["PinterestAdsAdapter", "manifest"]

# Auto-register with the global registry
registry.register(PinterestAdsAdapter)
