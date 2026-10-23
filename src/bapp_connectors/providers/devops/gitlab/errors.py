"""GitLab error mapping onto the framework hierarchy."""

from __future__ import annotations

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ProviderError, RateLimitError


class GitLabError(ProviderError):
    """Generic GitLab failure: a 5xx or an unexpected payload."""


class GitLabUnreachableError(ProviderError):
    """The server could not be reached at all: DNS, TLS, refused connection, timeout.

    Distinct from an error the server itself reported — nothing was executed.
    """


class GitLabNotFoundError(PermanentProviderError):
    """The project, group or issue does not exist — or the token may not see it.

    GitLab answers 404 instead of 403 for objects the token cannot read, so the two are
    reported together.
    """


def raise_for_status(status_code: int, body: str, url: str) -> None:
    """Raise the framework error matching a non-2xx GitLab answer; do nothing on 2xx."""
    if status_code < 400:
        return
    detail = (body or "")[:500]
    if status_code == 401:
        raise AuthenticationError(f"GitLab rejected the access token ({url}): {detail}")
    if status_code == 403:
        raise GitLabNotFoundError(f"GitLab resource forbidden or missing: {url}: {detail}", status_code=403)
    if status_code == 404:
        raise GitLabNotFoundError(f"GitLab resource not found: {url}: {detail}", status_code=404)
    if status_code == 429:
        raise RateLimitError(f"GitLab rate limit reached: {url}")
    if status_code >= 500:
        raise GitLabError(f"GitLab server error {status_code}: {url}: {detail}", status_code=status_code)
    # Remaining 4xx (400, 409, 422): the request itself is wrong, a retry will not help.
    raise PermanentProviderError(f"GitLab error {status_code}: {url}: {detail}", status_code=status_code)
