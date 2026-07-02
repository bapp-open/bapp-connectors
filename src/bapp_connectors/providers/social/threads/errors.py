"""
Threads API error mapping.

The Threads API uses Meta's Graph-style error bodies. HTTP-level errors
(401/429/4xx/5xx) are classified by the shared ResilientHttpClient; the API
can also return HTTP 200 with an ``{"error": {...}}`` body — ``check_payload``
maps those to framework errors.
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


def classify_threads_error(payload: dict) -> ConnectorError:
    """Map a Threads API error payload (``{"error": {...}}``) to a framework error."""
    error = payload.get("error", {}) or {}
    code = error.get("code")
    message = error.get("message", "Unknown Threads API error")

    if code == 190:
        return AuthenticationError(f"Threads access token invalid or expired: {message}")
    if code in _RATE_LIMIT_CODES:
        return RateLimitError(f"Threads rate limit exceeded (code {code}): {message}")
    if code == 100:
        return ValidationError(f"Threads API invalid parameter: {message}")
    return ProviderError(f"Threads API error (code {code}): {message}")


def check_payload(payload: dict | list | str) -> dict | list | str:
    """Raise a framework error if a Threads response body carries an error; return it otherwise."""
    if isinstance(payload, dict) and "error" in payload:
        raise classify_threads_error(payload)
    return payload
