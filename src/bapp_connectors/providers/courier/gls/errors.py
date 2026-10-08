"""
GLS-specific error mapping.

GLS answers HTTP 200 with the failures in an `...Error(s)/ErrorList` list of
`ErrorInfo` ({ErrorCode, ErrorDescription, ClientReferenceList, ParcelIdList}).
Codes from the MyGLS API documentation, Appendix A.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

AUTH_ERROR = -1
# "Same request sent 5 times within last 5 minutes"
DUPLICATE_REQUEST_ERROR = 31
# Unexpected exception / internal problem on the GLS side
SERVER_ERRORS = {1000, 1001}


class GLSError(ProviderError):
    """Base GLS error."""


def format_gls_errors(errors: list[dict]) -> str:
    parts = []
    for error in errors:
        text = f"[{error.get('ErrorCode')}] {error.get('ErrorDescription') or ''}".strip()
        refs = error.get("ClientReferenceList") or []
        if refs:
            text += f" (ref: {', '.join(str(r) for r in refs)})"
        parts.append(text)
    return "; ".join(parts)


def raise_for_gls_errors(errors: list[dict] | None, operation: str) -> None:
    """Raise the matching framework error when a GLS response carries an error list."""
    errors = [e for e in errors or [] if isinstance(e, dict) and e.get("ErrorCode") not in (None, 0)]
    if not errors:
        return
    message = f"GLS {operation}: {format_gls_errors(errors)}"
    codes = {e.get("ErrorCode") for e in errors}
    if AUTH_ERROR in codes:
        raise AuthenticationError(message)
    if DUPLICATE_REQUEST_ERROR in codes:
        raise RateLimitError(message)
    if codes <= SERVER_ERRORS:
        raise GLSError(message)
    raise ValidationError(message)
