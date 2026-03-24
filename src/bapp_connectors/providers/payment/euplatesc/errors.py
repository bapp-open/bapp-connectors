"""EuPlatesc-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
)


class EuPlatescError(ProviderError):
    """Base EuPlatesc error."""


class EuPlatescIPNError(EuPlatescError):
    """EuPlatesc IPN verification failed."""


def classify_euplatesc_error(status_code: int, body: str = "") -> EuPlatescError:
    if status_code in (401, 403):
        raise AuthenticationError(f"EuPlatesc auth failed: {body[:200]}", status_code=status_code)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"EuPlatesc client error {status_code}: {body[:500]}", status_code=status_code)
    raise EuPlatescError(f"EuPlatesc server error {status_code}: {body[:500]}")
