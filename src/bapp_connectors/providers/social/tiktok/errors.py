"""
TikTok-specific error mapping.

Every TikTok Display API v2 response carries an ``error`` envelope with a
string ``code``; ``"ok"`` means success. This module maps those codes to
framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

_AUTH_CODES = frozenset({"access_token_invalid", "access_token_expired", "scope_not_authorized"})
_VALIDATION_CODES = frozenset({"invalid_params", "invalid_file_upload"})


def check_response(payload: dict) -> dict:
    """Inspect a TikTok API envelope and return its ``data`` on success.

    Raises the appropriate framework error when ``error.code`` is not "ok".
    """
    if not isinstance(payload, dict):
        raise ProviderError(f"Unexpected TikTok response: {payload!r}")

    error = payload.get("error") or {}
    code = error.get("code", "ok")
    if code == "ok":
        return payload.get("data", {})

    message = error.get("message", "") or code
    if code in _AUTH_CODES:
        raise AuthenticationError(f"TikTok auth error ({code}): {message}")
    if code == "rate_limit_exceeded":
        raise RateLimitError(f"TikTok rate limit exceeded: {message}")
    if code in _VALIDATION_CODES:
        raise ValidationError(f"TikTok validation error ({code}): {message}")
    raise ProviderError(f"TikTok API error ({code}): {message}")
