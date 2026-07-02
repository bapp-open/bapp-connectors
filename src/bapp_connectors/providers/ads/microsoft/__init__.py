"""Microsoft Ads (Bing Ads) advertising provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.ads.microsoft.adapter import MicrosoftAdsAdapter
from bapp_connectors.providers.ads.microsoft.manifest import manifest

__all__ = ["MicrosoftAdsAdapter", "manifest"]

# Auto-register with the global registry
registry.register(MicrosoftAdsAdapter)
