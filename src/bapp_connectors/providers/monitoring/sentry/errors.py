"""Sentry error mapping onto the framework hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

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


def parse_retry_after(headers: Mapping[str, str] | None) -> int | None:
    """`Retry-After` as integer seconds; None when absent, negative or not a plain integer (e.g. an HTTP-date)."""
    for key, value in (headers or {}).items():
        if str(key).lower() == "retry-after":
            text = str(value or "").strip()
            return int(text) if text.isascii() and text.isdigit() else None
    return None


def raise_for_status(status_code: int, body: str, url: str, headers: Mapping[str, str] | None = None) -> None:
    """Raise the framework error matching a non-2xx Sentry answer; do nothing on 2xx.

    `headers` (the response's) feed `RateLimitError.retry_after` on a 429, which the retry
    policy waits for instead of its own backoff.
    """
    if status_code < 400:
        return
    detail = (body or "")[:500]
    if status_code == 401:
        raise AuthenticationError(f"Sentry rejected the auth token ({url}): {detail}")
    if status_code == 403:
        raise SentryNotFoundError(f"Sentry resource forbidden or missing: {url}: {detail}", status_code=403)
    if status_code == 404:
        raise SentryNotFoundError(f"Sentry resource not found: {url}: {detail}", status_code=404)
    if status_code == 409:
        # Only project creation answers 409 (slug taken); `SentryClient.create_project`
        # re-raises it naming the slug.
        raise ValidationError(f"Sentry conflict: {url}: {detail}", status_code=409)
    if status_code == 429:
        raise RateLimitError(f"Sentry rate limit reached: {url}", retry_after=parse_retry_after(headers))
    if status_code >= 500:
        raise SentryError(f"Sentry server error {status_code}: {url}: {detail}", status_code=status_code)
    # Remaining 4xx (400, 422): the request itself is wrong, a retry will not help.
    raise PermanentProviderError(f"Sentry error {status_code}: {url}: {detail}", status_code=status_code)


def reject_internal_error(payload: Any, url: str) -> None:
    """Raise `SentryError` when Sentry answered HTTP 200 with `{"detail": "Internal Error"}`.

    Self-hosted Sentry sporadically does this for perfectly valid GETs; the error is a
    `ProviderError`, so a retry policy around the call gets another try.
    """
    if payload == INTERNAL_ERROR_BODY:
        raise SentryError(f"Sentry answered 'Internal Error': {url}")


def slug_conflict_error(slug: str, cause: ValidationError) -> ValidationError:
    """The 409 of `POST teams/:org/:team/projects/`: the project slug is already taken."""
    return ValidationError(f"Sentry project slug already exists: {slug}", status_code=409, detail=str(cause))
