"""
Instagram Graph API error mapping.

HTTP-level errors (401/429/4xx/5xx) are classified by the shared
ResilientHttpClient. The Graph API can also return HTTP 200 with an
``{"error": {...}}`` body — ``check_payload`` maps those to framework errors.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

# Graph error codes that indicate throttling (API too many calls, user request
# limit, page request limit, custom rate limit).
_RATE_LIMIT_CODES = {4, 17, 32, 613}

# business_discovery answers an unknown username with code 110 / subcode 2207013
# ("Cannot find User") — on HTTP 400 or in a 200 error body.
_USER_NOT_FOUND_SUBCODE = 2207013


def classify_graph_error(payload: dict) -> ConnectorError:
    """Map a Graph API error payload (``{"error": {...}}``) to a framework error."""
    error = payload.get("error", {}) or {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    message = error.get("message", "Unknown Instagram Graph API error")

    if code == 190:
        return AuthenticationError(f"Instagram access token invalid or expired: {message}", error_subcode=subcode)
    if code in _RATE_LIMIT_CODES:
        return RateLimitError(f"Instagram rate limit exceeded (code {code}): {message}", error_subcode=subcode)
    if code == 100:
        return ValidationError(f"Instagram Graph API invalid parameter: {message}", error_subcode=subcode)
    return ProviderError(f"Instagram Graph API error (code {code}): {message}", error_subcode=subcode)


def is_user_not_found(error: ConnectorError) -> bool:
    """True when a business_discovery lookup failed because the username does not exist."""
    if getattr(error, "error_subcode", None) == _USER_NOT_FOUND_SUBCODE:
        return True
    # HTTP 400 responses are raised by the shared client with the raw body in the message.
    return str(_USER_NOT_FOUND_SUBCODE) in str(error)


def check_payload(payload: dict | list | str) -> dict | list | str:
    """Raise a framework error if a Graph response body carries an error; return it otherwise."""
    if isinstance(payload, dict) and "error" in payload:
        raise classify_graph_error(payload)
    return payload
