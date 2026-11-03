"""SAGA Web error mapping. Messages never carry the API key."""

from __future__ import annotations

from bapp_connectors.core.errors import AuthenticationError, ProviderError, ValidationError


class SagaWebError(ProviderError):
    """A SAGA Web call failed. The message is SAGA's own when it sent one."""

    def __init__(self, message: str = "", status_code: int | None = None, **kwargs):
        super().__init__(message, status_code=status_code, **kwargs)


class SagaWebAuthError(SagaWebError, AuthenticationError):
    """SAGA Web rejected the key (HTTP 401/403)."""

    # ProviderError comes first in the MRO and is retryable; a rejected key is not
    retryable = False


class SagaWebValidationError(SagaWebError, ValidationError):
    """SAGA Web refused the request parameters (HTTP 400)."""

    retryable = False
