"""
Meta Graph API client — the Facebook Graph client, shared.

Meta (Facebook Pages + Instagram) uses the same Graph API host and payload
shape as the ``facebook`` provider, so its raw HTTP client is reused as-is.
"""

from bapp_connectors.providers.social.facebook.client import FacebookGraphClient as MetaGraphClient

__all__ = ["MetaGraphClient"]
