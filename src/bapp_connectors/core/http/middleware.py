"""
Request/response middleware chain for observability and logging.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    """Context passed through the middleware chain for a single request."""

    method: str = ""
    url: str = ""
    headers: dict = field(default_factory=dict)
    kwargs: dict = field(default_factory=dict)
    started_at: float = 0.0
    provider: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class ResponseContext:
    """Context passed through the middleware chain after a response."""

    request: RequestContext = field(default_factory=RequestContext)
    status_code: int = 0
    body: Any = None
    duration_ms: int = 0
    error: Exception | None = None
    extra: dict = field(default_factory=dict)


# Middleware callback types
OnRequestCallback = Callable[[RequestContext], None]
OnResponseCallback = Callable[[ResponseContext], None]
OnErrorCallback = Callable[[RequestContext, Exception], None]


class MiddlewareChain:
    """Manages request/response/error middleware callbacks."""

    def __init__(self):
        self._on_request: list[OnRequestCallback] = []
        self._on_response: list[OnResponseCallback] = []
        self._on_error: list[OnErrorCallback] = []

    def add_on_request(self, callback: OnRequestCallback) -> None:
        self._on_request.append(callback)

    def add_on_response(self, callback: OnResponseCallback) -> None:
        self._on_response.append(callback)

    def add_on_error(self, callback: OnErrorCallback) -> None:
        self._on_error.append(callback)

    def fire_on_request(self, ctx: RequestContext) -> None:
        for cb in self._on_request:
            try:
                cb(ctx)
            except Exception:
                logger.exception("Error in on_request middleware")

    def fire_on_response(self, ctx: ResponseContext) -> None:
        for cb in self._on_response:
            try:
                cb(ctx)
            except Exception:
                logger.exception("Error in on_response middleware")

    def fire_on_error(self, req_ctx: RequestContext, error: Exception) -> None:
        for cb in self._on_error:
            try:
                cb(req_ctx, error)
            except Exception:
                logger.exception("Error in on_error middleware")


def logging_middleware() -> tuple[OnRequestCallback, OnResponseCallback, OnErrorCallback]:
    """Built-in logging middleware for debugging."""

    def on_request(ctx: RequestContext) -> None:
        logger.debug("[%s] %s %s", ctx.provider, ctx.method, ctx.url)

    def on_response(ctx: ResponseContext) -> None:
        logger.debug(
            "[%s] %s %s → %d (%dms)",
            ctx.request.provider,
            ctx.request.method,
            ctx.request.url,
            ctx.status_code,
            ctx.duration_ms,
        )

    def on_error(ctx: RequestContext, error: Exception) -> None:
        logger.warning("[%s] %s %s → ERROR: %s", ctx.provider, ctx.method, ctx.url, error)

    return on_request, on_response, on_error
