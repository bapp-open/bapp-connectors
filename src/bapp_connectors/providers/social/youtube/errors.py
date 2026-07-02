"""
YouTube-specific error helpers.

HTTP-level errors are already classified by the shared ResilientHttpClient
(quota errors arrive as 403 → AuthenticationError). These helpers cover the
Data API's habit of returning 200 with an empty ``items`` list for unknown IDs.
"""

from __future__ import annotations

from bapp_connectors.core.errors import PermanentProviderError


def first_item_or_not_found(items: list | None, what: str, entity_id: str) -> dict:
    """Return the first item of a Data API ``items`` list, or raise when empty.

    The YouTube Data API returns 200 with ``{"items": []}`` for unknown or
    inaccessible IDs, so a missing resource never surfaces as an HTTP error.
    """
    if not items:
        raise PermanentProviderError(f"YouTube {what} not found: {entity_id}")
    return items[0]
