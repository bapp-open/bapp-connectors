"""Maparea raspunsurilor Apple pe ierarhia de erori a framework-ului."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    WebhookVerificationError,
)


class AppleWebhookError(WebhookVerificationError):
    """Notificare App Store Server cu semnatura sau lant de certificate invalid."""


def raise_for_report_response(response, *, what: str) -> None:
    """Pentru apelurile cu `direct_response=True`; 404 e tratat de apelant (raport nepublicat)."""
    status = getattr(response, "status_code", 0)
    text = getattr(response, "text", "") or ""
    if status in (401, 403):
        raise AuthenticationError(f"Apple {what}: autentificare refuzata ({status}): {text[:200]}", status_code=status)
    if status == 429:
        raise RateLimitError(f"Apple {what}: rate limit")
    if 400 <= status < 500:
        raise PermanentProviderError(f"Apple {what}: {status} {text[:500]}", status_code=status)
    if status >= 500:
        raise ProviderError(f"Apple {what}: {status} {text[:500]}", status_code=status)
