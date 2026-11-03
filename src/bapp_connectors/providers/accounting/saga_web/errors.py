"""SAGA Web error mapping. Messages never carry the API key."""

from __future__ import annotations

from bapp_connectors.core.errors import AuthenticationError, ProviderError, ValidationError


class SagaWebError(ProviderError):
    """A SAGA Web call failed. The message is SAGA's own when it sent one.

    ``is_envelope`` is True when the body was SAGA's JSON envelope, i.e. SAGA itself answered
    (and so accepted the key); a proxy page, an HTML 404 or a transport failure leave it False.
    """

    is_envelope: bool = False

    def __init__(self, message: str = "", status_code: int | None = None, *, is_envelope: bool = False, **kwargs):
        super().__init__(message, status_code=status_code, **kwargs)
        self.is_envelope = is_envelope


class SagaWebAuthError(SagaWebError, AuthenticationError):
    """SAGA Web rejected the key (HTTP 401/403)."""

    # ProviderError comes first in the MRO and is retryable; a rejected key is not
    retryable = False


class SagaWebValidationError(SagaWebError, ValidationError):
    """SAGA Web refused the request parameters (HTTP 400)."""

    retryable = False


class SagaWebCredentialsNotSaved(SagaWebError):  # noqa: N818 — the name says what the host must do
    """SAGA issued a new key and ``on_credentials_update`` failed to store it.

    The old key is already blocked, so the run must stop; never retried, and the message never
    carries the key.
    """

    retryable = False
