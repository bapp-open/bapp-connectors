"""LibraPay-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ProviderError


class LibraPayError(ProviderError):
    """Base LibraPay error."""


def classify_librapay_error(status_code: int, body: str = "") -> LibraPayError:
    if status_code in (401, 403):
        raise AuthenticationError(f"LibraPay auth failed: {body[:200]}", status_code=status_code)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"LibraPay client error {status_code}: {body[:500]}", status_code=status_code)
    raise LibraPayError(f"LibraPay server error {status_code}: {body[:500]}")
