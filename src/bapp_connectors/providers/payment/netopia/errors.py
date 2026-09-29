"""
Netopia-specific error mapping.

Maps Netopia API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)

# Netopia answers refused operations with HTTP 200 and an ``error`` object, so
# the HTTP status says nothing. These codes are the non-failures: "00" approved,
# "100" 3-D Secure required, "101" redirect the customer to the payment page.
NETOPIA_OK_CODES = frozenset({"", "0", "00", "100", "101"})


class NetopiaError(ProviderError):
    """Base Netopia error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class NetopiaAPIError(NetopiaError):
    """Netopia returned an API error."""


class NetopiaPaymentError(NetopiaError):
    """Netopia payment operation failed."""


def classify_netopia_error(status_code: int, body: str = "", response=None) -> NetopiaError:
    """Map a Netopia HTTP error to the appropriate framework error."""
    if status_code == 401 or status_code == 403:
        raise AuthenticationError(
            f"Netopia authentication failed: {body[:200]}",
            status_code=status_code,
        )
    if status_code == 429:
        raise RateLimitError("Netopia rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(
            f"Netopia client error {status_code}: {body[:500]}",
            status_code=status_code,
        )
    raise NetopiaAPIError(
        f"Netopia server error {status_code}: {body[:500]}",
        response=response,
    )


class NetopiaOperationError(PermanentProviderError):
    """Netopia refused the operation (HTTP 200 with a failure ``error.code``).

    Permanent on purpose: a refused refund or void must not be retried blindly.
    """

    def __init__(self, message: str, *, code: str = "", response: dict | None = None):
        super().__init__(message)
        self.code = code
        self.response = response


def raise_for_netopia_error(data: dict | list | str, operation: str) -> None:
    """Raise NetopiaOperationError when a 200 response carries a failure code."""
    if not isinstance(data, dict):
        return
    error = data.get("error") or {}
    code = str(error.get("code") or "").strip()
    if code in NETOPIA_OK_CODES:
        return
    message = error.get("message") or "unknown error"
    raise NetopiaOperationError(f"Netopia {operation} refused ({code}): {message}", code=code, response=data)
