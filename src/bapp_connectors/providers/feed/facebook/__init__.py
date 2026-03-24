"""Facebook/Meta Commerce feed provider."""

from bapp_connectors.core.registry import registry

from .adapter import FacebookFeedAdapter

registry.register(FacebookFeedAdapter)
