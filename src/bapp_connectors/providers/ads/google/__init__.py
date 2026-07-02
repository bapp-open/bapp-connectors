"""Google Ads advertising provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.ads.google.adapter import GoogleAdsAdapter
from bapp_connectors.providers.ads.google.manifest import manifest

__all__ = ["GoogleAdsAdapter", "manifest"]

# Auto-register with the global registry
registry.register(GoogleAdsAdapter)
