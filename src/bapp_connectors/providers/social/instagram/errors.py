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


def classify_graph_error(payload: dict) -> ConnectorError:
    """Map a Graph API error payload (``{"error": {...}}``) to a framework error."""
    error = payload.get("error", {}) or {}
    code = error.get("code")
    message = error.get("message", "Unknown Instagram Graph API error")

    if code == 190:
        return AuthenticationError(f"Instagram access token invalid or expired: {message}")
    if code in _RATE_LIMIT_CODES:
        return RateLimitError(f"Instagram rate limit exceeded (code {code}): {message}")
    if code == 100:
        return ValidationError(f"Instagram Graph API invalid parameter: {message}")
    return ProviderError(f"Instagram Graph API error (code {code}): {message}")


def check_payload(payload: dict | list | str) -> dict | list | str:
    """Raise a framework error if a Graph response body carries an error; return it otherwise."""
    if isinstance(payload, dict) and "error" in payload:
        raise classify_graph_error(payload)
    return payload
