"""
HTTP client for the Graph API: reads the ``{"error": {...}}`` body of a 4xx.

The shared ResilientHttpClient classifies by HTTP status alone, which is wrong for
Graph: a permission error (code 10/200 — app review, Page role) arrives as HTTP 403
and would read as "token revoked", while an expired or revoked token (code 190)
usually arrives as HTTP 400 and would read as a plain client error. Here the Graph
error code decides; the status only matters when the body is not a Graph error.
Used by the facebook, meta and instagram providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.errors import ConnectorError, PermanentProviderError, ProviderError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.providers.social.facebook.errors import classify_graph_error

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests


def graph_http_error(
    payload: dict,
    status: int,
    classify: Callable[[dict], ConnectorError] = classify_graph_error,
) -> ConnectorError:
    """The framework error for a Graph error body that came with a 4xx ``status``.

    Code 190 → AuthenticationError, throttling codes → RateLimitError, code 100 →
    ValidationError (all from ``classify``). Any other code is a refusal that a retry
    won't change (permissions, unsupported request), so it becomes a
    PermanentProviderError with Meta's message — unless Meta flags it ``is_transient``.
    """
    error = payload.get("error") or {}
    exc = classify(payload)
    if type(exc) is ProviderError and not error.get("is_transient"):
        exc = PermanentProviderError(
            str(exc),
            status_code=status,
            error_code=error.get("code"),
            error_subcode=error.get("error_subcode"),
        )
    else:
        exc.status_code = status
    return exc


class GraphHttpClient(ResilientHttpClient):
    """ResilientHttpClient that classifies 4xx Graph error bodies by their error code."""

    def __init__(self, *args, classify: Callable[[dict], ConnectorError] = classify_graph_error, **kwargs):
        super().__init__(*args, **kwargs)
        self._classify_graph = classify

    def _classify_error(self, response: requests.Response) -> None:
        if 400 <= response.status_code < 500:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                raise graph_http_error(payload, response.status_code, self._classify_graph)
        super()._classify_error(response)
