"""Google Merchant Center feed provider."""

from bapp_connectors.core.registry import registry

from .adapter import GoogleMerchantFeedAdapter

registry.register(GoogleMerchantFeedAdapter)
