"""
Meta Graph API error mapping — shared with the ``facebook`` provider.

Same Graph API, same ``{"error": {...}}`` bodies, same error codes.
"""

from bapp_connectors.providers.social.facebook.errors import check_payload, classify_graph_error

__all__ = ["check_payload", "classify_graph_error"]
