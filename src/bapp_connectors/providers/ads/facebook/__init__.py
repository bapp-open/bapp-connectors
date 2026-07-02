"""Facebook/Meta Ads provider (Marketing API v19.0)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.ads.facebook.adapter import MetaAdsAdapter
from bapp_connectors.providers.ads.facebook.manifest import manifest

__all__ = ["MetaAdsAdapter", "manifest"]

# Auto-register with the global registry
registry.register(MetaAdsAdapter)
