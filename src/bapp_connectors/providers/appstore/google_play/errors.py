"""Maparea raspunsurilor Google (GCS, Android Publisher) pe erorile framework-ului."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    WebhookVerificationError,
)


class GooglePlayWebhookError(WebhookVerificationError):
    """Mesaj Pub/Sub invalid sau token OIDC respins."""


def raise_for_response(response, *, what: str) -> None:
    status = getattr(response, "status_code", 0)
    text = getattr(response, "text", "") or ""
    if status in (401, 403):
        raise AuthenticationError(f"Google Play {what}: acces refuzat ({status}): {text[:200]}", status_code=status)
    if status == 429:
        raise RateLimitError(f"Google Play {what}: rate limit")
    if 400 <= status < 500:
        raise PermanentProviderError(f"Google Play {what}: {status} {text[:500]}", status_code=status)
    if status >= 500:
        raise ProviderError(f"Google Play {what}: {status} {text[:500]}", status_code=status)
