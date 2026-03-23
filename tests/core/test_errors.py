"""Tests for the unified error hierarchy."""

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConfigurationError,
    ConnectorError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    UnsupportedFeatureError,
    ValidationError,
    WebhookVerificationError,
)


def test_retryable_flags():
    assert ConnectorError("test").retryable is False
    assert AuthenticationError("test").retryable is False
    assert ConfigurationError("test").retryable is False
    assert ValidationError("test").retryable is False
    assert RateLimitError("test").retryable is True
    assert ProviderError("test").retryable is True
    assert PermanentProviderError("test").retryable is False
    assert UnsupportedFeatureError("test").retryable is False
    assert WebhookVerificationError("test").retryable is False


def test_retryable_override():
    err = ConnectorError("test", retryable=True)
    assert err.retryable is True


def test_rate_limit_retry_after():
    err = RateLimitError("slow down", retry_after=30.0)
    assert err.retry_after == 30.0
    assert err.retryable is True


def test_provider_error_status_code():
    err = ProviderError("server error", status_code=503)
    assert err.status_code == 503


def test_error_inheritance():
    assert issubclass(AuthenticationError, ConnectorError)
    assert issubclass(RateLimitError, ConnectorError)
    assert issubclass(ProviderError, ConnectorError)
    assert issubclass(PermanentProviderError, ConnectorError)
