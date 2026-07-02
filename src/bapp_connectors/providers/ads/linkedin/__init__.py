"""LinkedIn Ads provider (LinkedIn Marketing API)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.ads.linkedin.adapter import LinkedInAdsAdapter
from bapp_connectors.providers.ads.linkedin.manifest import manifest

__all__ = ["LinkedInAdsAdapter", "manifest"]

# Auto-register with the global registry
registry.register(LinkedInAdsAdapter)
