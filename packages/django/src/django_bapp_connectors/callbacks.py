"""
Framework callbacks wired to Django models.

These functions are passed to the bapp_connectors HTTP client middleware
to persist execution logs and errors to Django models.
"""

from __future__ import annotations

import logging

from bapp_connectors.core.http.middleware import RequestContext, ResponseContext

logger = logging.getLogger(__name__)

# Only persist request/response bodies when the call is useful for debugging
# connectivity (errors, non-2xx). Daily successful traffic stores only metadata.
_PAYLOAD_MAX_BYTES = 8000
_SENSITIVE_KEYS = {"consumer_secret", "consumer_key", "password", "secret", "token", "access_token", "refresh_token", "authorization"}


def _redact(value):
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in _SENSITIVE_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _truncate(value):
    """JSON-safe value capped at _PAYLOAD_MAX_BYTES when serialized."""
    import json as _json
    try:
        encoded = _json.dumps(value, default=str)
    except Exception:
        encoded = str(value)
    if len(encoded) <= _PAYLOAD_MAX_BYTES:
        try:
            return _json.loads(encoded)
        except Exception:
            return encoded
    return {"_truncated": True, "preview": encoded[:_PAYLOAD_MAX_BYTES]}


def _extract_request_payload(ctx: RequestContext):
    kwargs = ctx.kwargs or {}
    for key in ("json", "data", "params"):
        if key in kwargs and kwargs[key]:
            return _truncate(_redact(kwargs[key]))
    return None


def make_execution_log_callback(execution_log_model, connection):
    """
    Create on_response and on_error callbacks that persist to ExecutionLog.

    Request/response bodies are stored only for debugging-relevant calls
    (non-2xx responses and errors); successful calls record metadata only.

    Usage:
        on_response, on_error = make_execution_log_callback(ExecutionLog, connection)
        middleware.add_on_response(on_response)
        middleware.add_on_error(on_error)
    """

    def on_response(ctx: ResponseContext):
        try:
            is_debug_worthy = not (200 <= ctx.status_code < 300)
            request_payload = _extract_request_payload(ctx.request) if is_debug_worthy else None
            response_payload = _truncate(_redact(ctx.body)) if is_debug_worthy and ctx.body is not None else None

            execution_log_model.objects.create(
                connection=connection,
                action=f"{ctx.request.method} {ctx.request.url}",
                method=ctx.request.method,
                url=ctx.request.url[:500],
                response_status=ctx.status_code,
                duration_ms=ctx.duration_ms,
                request_payload=request_payload,
                response_payload=response_payload,
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
                request_payload=_extract_request_payload(ctx),
            )
        except Exception:
            logger.exception("Failed to log execution error")

    return on_response, on_error
