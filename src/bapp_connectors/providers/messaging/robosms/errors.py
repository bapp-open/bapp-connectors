"""
RoboSMS-specific error mapping.

Maps RoboSMS API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class RoboSMSError(ProviderError):
    """Base RoboSMS error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class RoboSMSAPIError(RoboSMSError):
    """RoboSMS returned an API error."""


def classify_robosms_error(status_code: int, body: str = "", response=None) -> RoboSMSError:
    """Map a RoboSMS HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"RoboSMS authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("RoboSMS rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"RoboSMS client error {status_code}: {body[:500]}", status_code=status_code)
    raise RoboSMSAPIError(f"RoboSMS server error {status_code}: {body[:500]}", response=response)
