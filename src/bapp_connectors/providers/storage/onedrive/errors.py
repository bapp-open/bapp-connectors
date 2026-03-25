"""OneDrive-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class OneDriveError(ProviderError):
    """Base OneDrive error."""


class OneDriveAPIError(OneDriveError):
    """OneDrive returned an API error."""


def classify_onedrive_error(status_code: int, body: str = "", response=None) -> OneDriveError:
    if status_code in (401, 403):
        raise AuthenticationError(f"OneDrive authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("OneDrive rate limit exceeded")
    if status_code == 404:
        raise PermanentProviderError(f"OneDrive item not found: {body[:500]}", status_code=status_code)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"OneDrive client error {status_code}: {body[:500]}", status_code=status_code)
    raise OneDriveAPIError(f"OneDrive server error {status_code}: {body[:500]}")
