"""pfSense error mapping onto the framework hierarchy."""

from __future__ import annotations

from bapp_connectors.core.errors import PermanentProviderError, ProviderError


class PfSenseError(ProviderError):
    """Generic pfSense failure (transport or unexpected payload)."""


class PfSenseFaultError(PermanentProviderError):
    """The XML-RPC call returned a fault (bad PHP, unknown method, ...)."""

    def __init__(self, message: str = "", *, fault_code: int | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.fault_code = fault_code


class PfSenseUnreachableError(ProviderError):
    """Every configured endpoint failed at transport level."""

    retryable = True

    def __init__(self, message: str = "", *, attempts: list[str] | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.attempts = attempts or []
