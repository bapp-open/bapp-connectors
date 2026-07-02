"""
Pinterest API v5 error mapping.

HTTP-level errors (401/403/404/429/5xx) are classified by the shared
ResilientHttpClient. Pinterest error bodies are ``{"code": int, "message": str}``
— ``error_message`` renders them for messages, and ``not_found`` builds the
framework error for pins that come back without an id.
"""

from __future__ import annotations

from bapp_connectors.core.errors import PermanentProviderError


def error_message(payload: object) -> str:
    """Render a Pinterest error body (``{"code": int, "message": str}``) as a message."""
    if isinstance(payload, dict):
        code = payload.get("code")
        message = payload.get("message", "")
        if code is not None or message:
            return f"Pinterest API error (code {code}): {message}"
    return f"Unexpected Pinterest response: {payload!r}"


def not_found(resource: str) -> PermanentProviderError:
    """Build the framework error for a missing Pinterest resource."""
    return PermanentProviderError(f"Pinterest resource not found: {resource}", status_code=404)
