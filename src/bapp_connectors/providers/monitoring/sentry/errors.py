"""Sentry error mapping onto the framework hierarchy."""

from __future__ import annotations

from typing import Any

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ProviderError, RateLimitError

INTERNAL_ERROR_BODY = {"detail": "Internal Error"}


class SentryError(ProviderError):
    """Generic Sentry failure: a 5xx, an 'Internal Error' body or an unexpected payload."""


class SentryUnreachableError(ProviderError):
    """The server could not be reached at all: DNS, TLS, refused connection, timeout.

    Distinct from an error the server itself reported — nothing was executed.
    """


class SentryNotFoundError(PermanentProviderError):
    """The organization, project or issue does not exist — or the token may not see it.

    Sentry answers 403 or 404 depending on the endpoint for objects outside the token's
    scope, so the two are reported together.
    """


def raise_for_status(status_code: int, body: str, url: str) -> None:
    """Raise the framework error matching a non-2xx Sentry answer; do nothing on 2xx."""
    if status_code < 400:
        return
    detail = (body or "")[:500]
    if status_code == 401:
        raise AuthenticationError(f"Sentry rejected the auth token ({url}): {detail}")
    if status_code == 403:
        raise SentryNotFoundError(f"Sentry resource forbidden or missing: {url}: {detail}", status_code=403)
    if status_code == 404:
        raise SentryNotFoundError(f"Sentry resource not found: {url}: {detail}", status_code=404)
    if status_code == 429:
        raise RateLimitError(f"Sentry rate limit reached: {url}")
    if status_code >= 500:
        raise SentryError(f"Sentry server error {status_code}: {url}: {detail}", status_code=status_code)
    # Remaining 4xx (400, 409, 422): the request itself is wrong, a retry will not help.
    raise PermanentProviderError(f"Sentry error {status_code}: {url}: {detail}", status_code=status_code)


def reject_internal_error(payload: Any, url: str) -> None:
    """Raise `SentryError` when Sentry answered HTTP 200 with `{"detail": "Internal Error"}`.

    Self-hosted Sentry sporadically does this for perfectly valid GETs; the error is a
    `ProviderError`, so a retry policy around the call gets another try.
    """
    if payload == INTERNAL_ERROR_BODY:
        raise SentryError(f"Sentry answered 'Internal Error': {url}")
