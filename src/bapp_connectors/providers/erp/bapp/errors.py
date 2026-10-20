"""BAPP ERP error mapping. Messages never carry credentials."""

from __future__ import annotations

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError


class BappErpError(PermanentProviderError):
    """A BAPP task failed. The message is the ERP's own, unchanged."""


class BappErpAuthError(BappErpError, AuthenticationError):
    """BAPP rejected the token (HTTP 401/403)."""
