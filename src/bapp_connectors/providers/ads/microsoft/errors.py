"""
Microsoft Ads (Bing Ads) specific error helpers.

The Bing Ads API v13 is SOAP: application errors arrive as ``soap:Fault``
envelopes (often with HTTP 500, even for auth problems) carrying
``AdApiError`` / ``OperationError`` / ``BatchError`` elements with numeric
``Code`` values. Classification is deliberately permissive and string-based —
we only need to distinguish auth, throttling, and permanent vs retryable.
"""

from __future__ import annotations

import re
from typing import NoReturn

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)

# AdApiError codes: 105 InvalidCredentials, 106 UserIsNotAuthorized, 117 CallRateExceeded.
_AUTH_CODES = {"105", "106"}
_THROTTLE_CODES = {"117"}

_CODE_RE = re.compile(r"<Code[^>]*>(\d+)</Code>")
_MESSAGE_RE = re.compile(r"<(?:faultstring|Message)[^>]*>([^<]+)<", re.IGNORECASE)


def classify_soap_fault(text: str, status: int | None = None) -> NoReturn:
    """Classify a SOAP fault / error response into a framework error. Always raises.

    Args:
        text: The raw SOAP response body (fault envelope or partial-error XML).
        status: The HTTP status code, when known. Bing frequently returns 500
            even for auth faults, so code/string checks take precedence.
    """
    codes = set(_CODE_RE.findall(text))
    match = _MESSAGE_RE.search(text)
    message = match.group(1).strip() if match else text[:200]
    lowered = text.lower()

    if codes & _AUTH_CODES or "authenticationtoken" in lowered or "invalidcredentials" in lowered:
        raise AuthenticationError(f"Microsoft Ads authentication failed: {message}", status_code=status)

    if codes & _THROTTLE_CODES or "throttl" in lowered:
        raise RateLimitError(f"Microsoft Ads throttled the request: {message}")

    if status is not None and 400 <= status < 500:
        raise PermanentProviderError(f"Microsoft Ads rejected the request: {message}", status_code=status)

    raise ProviderError(f"Microsoft Ads SOAP fault: {message}", status_code=status)


def not_found(entity: str, entity_id: str) -> NoReturn:
    """Raise a PermanentProviderError for an entity that no Get* call returned."""
    raise PermanentProviderError(f"Microsoft Ads {entity} '{entity_id}' not found.", status_code=404)
