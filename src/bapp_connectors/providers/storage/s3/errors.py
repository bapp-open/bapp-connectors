"""
S3-specific error mapping.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
)


class S3Error(ProviderError):
    """Base S3 error."""


class S3BucketError(S3Error):
    """S3 bucket-level error (not found, access denied)."""


def classify_s3_error(error_code: str, message: str = "") -> S3Error:
    """Map an S3 error code to the appropriate framework error."""
    if error_code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"):
        raise AuthenticationError(f"S3 authentication failed: {error_code} {message[:200]}")
    if error_code in ("NoSuchBucket", "NoSuchKey"):
        raise PermanentProviderError(f"S3 not found: {error_code} {message[:200]}")
    raise S3Error(f"S3 error: {error_code} {message[:500]}")
