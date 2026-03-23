"""
eMAG-specific error mapping.

Maps eMAG API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConfigurationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class EmagError(ProviderError):
    """Base eMAG error."""

    def __init__(self, message: str, response=None, status_code: int | None = None):
        sc = status_code or (response.status_code if response else None)
        super().__init__(message, status_code=sc)
        self.response = response


class EmagIPWhitelistError(ConfigurationError):
    """eMAG rejected the request due to IP whitelist restrictions."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "IP address not whitelisted on eMAG. Add your server IP in the eMAG marketplace portal."
        )


_IP_WHITELIST_MARKERS = (
    "ip is not",
    "ip not whitelisted",
    "ip address is not allowed",
    "not allowed to access",
)


def classify_emag_error(status_code: int, body: str = "", response=None) -> EmagError:
    """Map an eMAG HTTP error to the appropriate framework error."""
    body_lower = body.lower()

    # IP whitelist errors can appear as 401/403
    for marker in _IP_WHITELIST_MARKERS:
        if marker in body_lower:
            raise EmagIPWhitelistError(f"eMAG IP whitelist error: {body[:500]}")

    if status_code == 401:
        raise AuthenticationError(f"eMAG authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 403:
        raise AuthenticationError(f"eMAG access denied: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("eMAG rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"eMAG client error {status_code}: {body[:500]}", status_code=status_code)
    raise EmagError(f"eMAG server error {status_code}: {body[:500]}", response=response, status_code=status_code)
