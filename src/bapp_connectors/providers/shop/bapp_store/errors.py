"""
Company Store error mapping: HTTP status -> framework error.
"""

from __future__ import annotations

from bapp_connectors.core.errors import AuthenticationError, ConnectorError, PermanentProviderError, ProviderError


def map_error(status: int, body: str) -> ConnectorError:
    detail = body[:500]
    if status in (401, 403):
        return AuthenticationError(f"Company Store rejected the sync token: {status} {detail}", status_code=status)
    if 400 <= status < 500:
        return PermanentProviderError(f"Company Store client error {status}: {detail}", status_code=status)
    return ProviderError(f"Company Store server error {status}: {detail}", status_code=status, retryable=True)


def raise_for_status(response) -> None:
    if response.ok:
        return
    raise map_error(response.status_code, response.text)
