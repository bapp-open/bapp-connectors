"""
TikTok Ads error mapping.

TikTok Business API responses always come back as HTTP 200 with an envelope:
    {"code": 0, "message": "OK", "request_id": "...", "data": {...}}
A non-zero ``code`` signals an error. This module maps those application-level
codes onto the framework error hierarchy.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

# Invalid/expired/missing access token and permission codes.
AUTH_ERROR_CODES = {40100, 40101, 40102, 40104, 40105}

# Request throttling codes (also detected by message, see check_response).
RATE_LIMIT_CODES = {40016, 40033}

# Malformed/invalid request payload codes.
VALIDATION_CODES = {40001, 40002, 40007}


def check_response(payload: dict) -> dict:
    """Validate a TikTok Business API envelope and return its ``data`` field.

    Raises the appropriate framework error for a non-zero ``code``:

    - codes in AUTH_ERROR_CODES → AuthenticationError
    - codes in RATE_LIMIT_CODES or a message containing "rate limit" /
      "too many requests" (case-insensitive) → RateLimitError
    - codes in VALIDATION_CODES → ValidationError
    - other 4xxxx codes → PermanentProviderError
    - 5xxxx and anything else → ProviderError
    """
    code = payload.get("code", -1)
    message = str(payload.get("message", ""))

    if code == 0:
        return payload.get("data", {})

    text = f"TikTok Ads API error {code}: {message}"
    lowered = message.lower()

    if code in AUTH_ERROR_CODES:
        raise AuthenticationError(text)
    if code in RATE_LIMIT_CODES or "rate limit" in lowered or "too many requests" in lowered:
        raise RateLimitError(text)
    if code in VALIDATION_CODES:
        raise ValidationError(text)
    if isinstance(code, int) and 40000 <= code < 50000:
        raise PermanentProviderError(text)
    raise ProviderError(text)
