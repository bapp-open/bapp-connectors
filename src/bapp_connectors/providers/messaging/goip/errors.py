"""
GoIP-specific error mapping.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
)


class GoIPError(ProviderError):
    """Base GoIP error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class GoIPDeviceError(GoIPError):
    """GoIP device returned an error (busy, unreachable, etc.)."""


def classify_goip_error(status_code: int, body: str = "", response=None) -> GoIPError:
    """Map a GoIP HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"GoIP authentication failed: {body[:200]}", status_code=status_code)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"GoIP client error {status_code}: {body[:500]}", status_code=status_code)
    raise GoIPDeviceError(f"GoIP device error {status_code}: {body[:500]}", response=response)
