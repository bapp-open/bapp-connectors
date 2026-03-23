"""
Framework callbacks wired to Django models.

These functions are passed to the bapp_connectors HTTP client middleware
to persist execution logs and errors to Django models.
"""

from __future__ import annotations

import logging

from bapp_connectors.core.http.middleware import RequestContext, ResponseContext

logger = logging.getLogger(__name__)


def make_execution_log_callback(execution_log_model, connection):
    """
    Create on_response and on_error callbacks that persist to ExecutionLog.

    Usage:
        on_response, on_error = make_execution_log_callback(ExecutionLog, connection)
        middleware.add_on_response(on_response)
        middleware.add_on_error(on_error)
    """

    def on_response(ctx: ResponseContext):
        try:
            execution_log_model.objects.create(
                connection=connection,
                action=f"{ctx.request.method} {ctx.request.url}",
                method=ctx.request.method,
                url=ctx.request.url[:500],
                response_status=ctx.status_code,
                duration_ms=ctx.duration_ms,
            )
        except Exception:
            logger.exception("Failed to log execution")

    def on_error(ctx: RequestContext, error: Exception):
        try:
            execution_log_model.objects.create(
                connection=connection,
                action=f"{ctx.method} {ctx.url}",
                method=ctx.method,
                url=ctx.url[:500],
                error=str(error)[:2000],
            )
        except Exception:
            logger.exception("Failed to log execution error")

    return on_response, on_error
