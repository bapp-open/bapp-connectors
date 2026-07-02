"""
LinkedIn REST API error mapping.

HTTP-level errors (401/429/4xx/5xx) are classified by the shared
ResilientHttpClient; LinkedIn error bodies carry
``{"message": ..., "serviceErrorCode": ..., "status": ...}`` and end up in
the framework error message. This module adds the collection-response helper
for endpoints that return ``{"elements": [...]}`` with HTTP 200 even when
the requested entity yields no results.
"""

from __future__ import annotations

from bapp_connectors.core.errors import PermanentProviderError


def first_element_or_not_found(payload: dict, what: str, entity_id: str) -> dict:
    """Return the first item of a LinkedIn ``elements`` collection response.

    LinkedIn finder endpoints (share statistics, ...) return HTTP 200 with an
    empty ``elements`` list when the entity does not exist or is not visible
    to the token — raise a non-retryable error in that case.
    """
    elements = payload.get("elements") or []
    if not elements:
        raise PermanentProviderError(f"LinkedIn returned no {what} for '{entity_id}'")
    return elements[0]
