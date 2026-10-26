"""Temu error mapping.

Temu answers HTTP 200 for everything and signals failure with ``success=false`` +
``errorCode``/``errorMsg``/``requestId``; this module turns those codes into the framework's
error hierarchy.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
    RateLimitError,
    UnsupportedFeatureError,
    ValidationError,
)

#: no access_token in body / token lacks the API scope / token expired or invalid
AUTH_CODES = frozenset({3000030, 3000032, 7000013})
#: parameter is illegal / invalid request parameters / invalid parameter / required parameter missing
VALIDATION_CODES = frozenset({130010001, 150010003, 200040002, 200040003})
#: service not supported (finance reports) / not a self-issued-invoice merchant
UNSUPPORTED_CODES = frozenset({200040005, 200030004})
#: try again later
RATE_LIMIT_CODES = frozenset({150010005})
#: ``bg.order.shippinginfo.v2.get`` on a cancelled order (live 2026-10-26: every status-3 order): Temu hides the
#: buyer once the order is cancelled. Not an error of ours — the order is imported without a contact.
SHIPPING_HIDDEN_CODE = 180020006


class TemuError(ProviderError):
    """Temu returned ``success=false`` with a code this module does not classify further."""

    def __init__(self, message: str, *, error_code: int = 0, request_id: str = "", **kwargs):
        super().__init__(message, **kwargs)
        self.error_code = error_code
        self.request_id = request_id


def classify_temu_error(error_code: int, message: str, request_id: str = "", api_type: str = "") -> ConnectorError:
    """Return (never raise) the framework error for a Temu error response."""
    text = f"Temu {api_type or 'API'} error {error_code}: {message}".strip()
    if request_id:
        text = f"{text} (requestId {request_id})"
    if error_code in AUTH_CODES:
        return AuthenticationError(text)
    if error_code in VALIDATION_CODES:
        return ValidationError(text)
    if error_code in UNSUPPORTED_CODES:
        return UnsupportedFeatureError(text)
    if error_code in RATE_LIMIT_CODES:
        return RateLimitError(text)
    return TemuError(text, error_code=error_code, request_id=request_id)
