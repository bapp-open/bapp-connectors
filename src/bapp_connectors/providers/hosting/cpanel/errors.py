"""cPanel error mapping onto the framework hierarchy.

UAPI answers HTTP 200 even when a call fails, so every error arrives as a string
inside the envelope. These classes exist so callers can tell apart the failures a
user can fix from the ones they cannot.
"""

from __future__ import annotations

import re

from bapp_connectors.core.errors import AuthenticationError, ConnectorError, PermanentProviderError, ProviderError


class CpanelError(ProviderError):
    """Generic cPanel failure (transport or unexpected payload)."""


class CpanelUnreachableError(ProviderError):
    """The server could not be reached at all: DNS, TLS, refused connection, timeout.

    Distinct from an error the server itself reported — nothing was executed.
    """


class CpanelFunctionUnavailableError(PermanentProviderError):
    """The server does not expose this UAPI module or function."""


class CpanelNotFoundError(PermanentProviderError):
    """The addressed object (mailbox, domain, zone) does not exist."""


class CpanelWeakPasswordError(PermanentProviderError):
    """The password was rejected by the server's strength policy.

    Recoverable by the user: pick a stronger password.
    """


class DnsZoneChangedError(PermanentProviderError):
    """The zone changed since it was read; the submitted serial is stale.

    Recoverable by the user: reload the zone and redo the edit.
    """


_FUNCTION_MISSING = re.compile(r"could not find the function", re.I)
_NOT_FOUND = re.compile(r"do not have an email account named|does not exist", re.I)
_WEAK_PASSWORD = re.compile(r"strength rating", re.I)
_STALE_SERIAL = re.compile(r"serial number .* does not match", re.I)
_DENIED = re.compile(r"access denied|permission denied|not authorized", re.I)


def classify_uapi_error(message: str) -> ConnectorError:
    """Map a UAPI error string onto the framework's error hierarchy."""
    if _STALE_SERIAL.search(message):
        return DnsZoneChangedError(message)
    if _WEAK_PASSWORD.search(message):
        return CpanelWeakPasswordError(message)
    if _FUNCTION_MISSING.search(message):
        return CpanelFunctionUnavailableError(message)
    if _NOT_FOUND.search(message):
        return CpanelNotFoundError(message)
    if _DENIED.search(message):
        return AuthenticationError(message)
    return CpanelError(message)
