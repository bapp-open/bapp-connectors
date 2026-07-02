"""
Facebook/Meta Ads error mapping.

Maps Graph API error payloads to framework error types. The Graph API can
return an ``{"error": {...}}`` body even with a 200 status code, so the client
runs every parsed dict response through :func:`check_payload`.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

# Graph API codes that indicate throttling (4/17/32/613 + the 80000-80007 family).
RATE_LIMIT_CODES = {4, 17, 32, 613}


def check_payload(payload: dict) -> None:
    """Raise the appropriate framework error if a Graph API payload carries an error.

    Graph API error bodies look like::

        {"error": {"message": "...", "type": "OAuthException", "code": 190, "error_subcode": 463}}
    """
    error = payload.get("error")
    if not isinstance(error, dict):
        return

    code = error.get("code")
    if isinstance(code, str) and code.isdigit():
        code = int(code)
    message = error.get("message", "Unknown Graph API error")
    subcode = error.get("error_subcode")
    detail = f"Meta Graph API error {code}"
    if subcode:
        detail += f" (subcode {subcode})"
    detail += f": {message}"

    if code == 190:
        raise AuthenticationError(detail)
    if code in RATE_LIMIT_CODES or str(code).startswith("8000"):
        raise RateLimitError(detail)
    if code == 100:
        raise ValidationError(detail)
    raise ProviderError(detail)
