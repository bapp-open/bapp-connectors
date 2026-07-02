"""
LinkedIn Ads specific error helpers.

HTTP-level errors (401/403 auth, 429 rate limit, other 4xx/5xx) are already
classified into framework errors by ResilientHttpClient. These helpers cover
LinkedIn specifics: responses read with ``direct_response=True`` (creates that
return the id in the ``x-restli-id`` header) bypass that classification, so
:func:`check_response` re-applies it while surfacing LinkedIn's
``{"message", "serviceErrorCode"}`` error body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

if TYPE_CHECKING:
    from typing import NoReturn

    import requests


def not_found(entity: str, entity_id: str) -> NoReturn:
    """Raise a PermanentProviderError for a LinkedIn entity that could not be resolved."""
    raise PermanentProviderError(f"LinkedIn Ads {entity} '{entity_id}' not found.", status_code=404)


def _error_detail(response: requests.Response) -> str:
    """Build a readable error message from a LinkedIn error body.

    LinkedIn error bodies look like::

        {"message": "...", "serviceErrorCode": 100, "status": 403}
    """
    detail = f"LinkedIn API error {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        if (code := body.get("serviceErrorCode")) is not None:
            detail += f" (serviceErrorCode {code})"
        if message := body.get("message"):
            detail += f": {message}"
    return detail


def check_response(response: requests.Response) -> None:
    """Raise the appropriate framework error for a failed direct response."""
    if response.ok:
        return
    status = response.status_code
    detail = _error_detail(response)
    if status in (401, 403):
        raise AuthenticationError(detail, status_code=status)
    if status == 429:
        raise RateLimitError(detail)
    if status in (400, 422):
        raise ValidationError(detail)
    if 400 <= status < 500:
        raise PermanentProviderError(detail, status_code=status)
    raise ProviderError(detail, status_code=status)
