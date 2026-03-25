"""Google Drive-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class GoogleDriveError(ProviderError):
    """Base Google Drive error."""


class GoogleDriveAPIError(GoogleDriveError):
    """Google Drive returned an API error."""


def classify_google_drive_error(status_code: int, body: str = "", response=None) -> GoogleDriveError:
    if status_code in (401, 403):
        raise AuthenticationError(f"Google Drive authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Google Drive rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Google Drive client error {status_code}: {body[:500]}", status_code=status_code)
    raise GoogleDriveAPIError(f"Google Drive server error {status_code}: {body[:500]}")
