"""Tests for make_execution_log_callback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bapp_connectors.core.http.middleware import RequestContext, ResponseContext
from django_bapp_connectors.callbacks import make_execution_log_callback

from tests.testapp.models import Connection, ExecutionLog


@pytest.fixture
def connection(db):
    return Connection.objects.create(
        provider_family="shop",
        provider_name="woocommerce",
        display_name="Test Shop",
        is_enabled=True,
        is_connected=True,
    )


@pytest.fixture
def callbacks(connection):
    """Return (on_response, on_error) callbacks bound to a connection."""
    return make_execution_log_callback(ExecutionLog, connection)


@pytest.fixture
def response_ctx():
    """Build a ResponseContext with realistic data."""
    req = RequestContext(
        method="GET",
        url="https://example.com/wp-json/wc/v3/orders",
        provider="woocommerce",
    )
    return ResponseContext(
        request=req,
        status_code=200,
        duration_ms=142,
    )


@pytest.fixture
def request_ctx():
    """Build a RequestContext for error callbacks."""
    return RequestContext(
        method="POST",
        url="https://example.com/wp-json/wc/v3/products",
        provider="woocommerce",
    )


# ── on_response ──


class TestOnResponse:
    def test_creates_execution_log_with_correct_fields(self, callbacks, response_ctx, connection):
        on_response, _on_error = callbacks

        on_response(response_ctx)

        log = ExecutionLog.objects.get(connection=connection)
        assert log.action == "GET https://example.com/wp-json/wc/v3/orders"
        assert log.method == "GET"
        assert log.url == "https://example.com/wp-json/wc/v3/orders"
        assert log.response_status == 200
        assert log.duration_ms == 142

    def test_truncates_url_to_500_chars(self, callbacks, connection):
        on_response, _on_error = callbacks

        long_url = "https://example.com/" + "x" * 600
        req = RequestContext(method="GET", url=long_url, provider="woocommerce")
        ctx = ResponseContext(request=req, status_code=200, duration_ms=50)

        on_response(ctx)

        log = ExecutionLog.objects.get(connection=connection)
        assert len(log.url) == 500
        assert log.url == long_url[:500]

    def test_swallows_exceptions(self, connection):
        """on_response should never raise, even if DB write fails."""
        on_response, _on_error = make_execution_log_callback(ExecutionLog, connection)

        req = RequestContext(method="GET", url="https://example.com/api", provider="test")
        ctx = ResponseContext(request=req, status_code=200, duration_ms=10)

        with patch.object(ExecutionLog.objects, "create", side_effect=Exception("DB down")):
            # Should not raise
            on_response(ctx)


# ── on_error ──


class TestOnError:
    def test_creates_execution_log_with_error_field(self, callbacks, request_ctx, connection):
        _on_response, on_error = callbacks

        on_error(request_ctx, ValueError("Something went wrong"))

        log = ExecutionLog.objects.get(connection=connection)
        assert log.action == "POST https://example.com/wp-json/wc/v3/products"
        assert log.method == "POST"
        assert log.url == "https://example.com/wp-json/wc/v3/products"
        assert log.error == "Something went wrong"
        assert log.response_status is None
        assert log.duration_ms is None

    def test_truncates_error_to_2000_chars(self, callbacks, request_ctx, connection):
        _on_response, on_error = callbacks

        long_error = "E" * 3000
        on_error(request_ctx, Exception(long_error))

        log = ExecutionLog.objects.get(connection=connection)
        assert len(log.error) == 2000
        assert log.error == long_error[:2000]

    def test_swallows_exceptions(self, connection):
        """on_error should never raise, even if DB write fails."""
        _on_response, on_error = make_execution_log_callback(ExecutionLog, connection)

        ctx = RequestContext(method="GET", url="https://example.com/api", provider="test")

        with patch.object(ExecutionLog.objects, "create", side_effect=Exception("DB down")):
            # Should not raise
            on_error(ctx, RuntimeError("API timeout"))
