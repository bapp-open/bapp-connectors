"""
Unified error hierarchy for the connector framework.

All connector errors inherit from ConnectorError and declare whether they are retryable.
Provider adapters should map their native errors to these framework errors.
"""

from __future__ import annotations


class ConnectorError(Exception):
    """Base for all connector errors."""

    retryable: bool = False

    def __init__(self, message: str = "", *, retryable: bool | None = None, **kwargs):
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable
        for key, value in kwargs.items():
            setattr(self, key, value)


class AuthenticationError(ConnectorError):
    """Invalid or expired credentials (401, 403 on auth endpoints)."""

    retryable = False


class ConfigurationError(ConnectorError):
    """Missing config, IP not whitelisted, invalid manifest, etc."""

    retryable = False


class ValidationError(ConnectorError):
    """Invalid request payload sent to provider."""

    retryable = False


class RateLimitError(ConnectorError):
    """429 or provider-specific throttling."""

    retryable = True
    retry_after: float | None = None

    def __init__(self, message: str = "", *, retry_after: float | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ProviderError(ConnectorError):
    """Provider returned a server error (5xx, unexpected). Retryable by default."""

    retryable = True
    status_code: int | None = None

    def __init__(self, message: str = "", *, status_code: int | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.status_code = status_code


class PermanentProviderError(ConnectorError):
    """Provider error that will not resolve on retry (4xx non-auth)."""

    retryable = False
    status_code: int | None = None

    def __init__(self, message: str = "", *, status_code: int | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.status_code = status_code


class UnsupportedFeatureError(ConnectorError):
    """Adapter doesn't support the requested capability."""

    retryable = False


class WebhookVerificationError(ConnectorError):
    """Webhook signature verification failed."""

    retryable = False


class ConnectionTestError(ConnectorError):
    """Connection test failed."""

    retryable = False
