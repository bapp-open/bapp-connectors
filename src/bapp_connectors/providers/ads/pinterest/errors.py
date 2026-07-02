"""
Pinterest Ads error helpers.

Pinterest API v5 error bodies are ``{"code": int, "message": str}`` and always
arrive with a matching non-2xx HTTP status, so the transport-level
classification (401 → AuthenticationError, 429 → RateLimitError, ...) is
already done by ResilientHttpClient. This module only carries small helpers
for the bulk-style write envelopes, whose per-item ``exceptions`` reuse the
same ``{"code", "message"}`` shape inside an HTTP 200 response.
"""

from __future__ import annotations

from bapp_connectors.core.errors import ValidationError


def error_text(body: dict) -> str:
    """Format a Pinterest ``{"code": int, "message": str}`` error body."""
    return f"Pinterest Ads API error {body.get('code')}: {body.get('message', '')}"


def check_item(item: dict) -> dict:
    """Unwrap one entry of a bulk-style write response ``{"items": [...]}``.

    Pinterest v5 write endpoints take list bodies and may wrap each result in
    ``{"data": {...}, "exceptions": [...]}``. Raises ValidationError when the
    item carries per-item exceptions; otherwise returns the entity payload.
    """
    exceptions = item.get("exceptions") or []
    if exceptions:
        raise ValidationError(error_text(exceptions[0]))
    data = item.get("data")
    return data if isinstance(data, dict) else item
