"""
Errors shared by the storage providers.

Provider-specific mapping stays in each provider's own ``errors.py``; what lives here
is the handful of conditions that are the same whatever the protocol is.
"""

from __future__ import annotations

from bapp_connectors.core.errors import PermanentProviderError


class FileTooLargeError(PermanentProviderError):
    """A download was stopped because it passed the caller's byte ceiling.

    Raised only when a ``max_bytes`` was asked for. Not retryable: the file will be
    the same size on the next attempt, so the caller has to raise the ceiling or stop
    reading that file.

    ``size`` is the file's real size when the server told us beforehand (SFTP, where a
    ``stat`` precedes the transfer) and ``None`` when the ceiling was hit mid-stream
    and all we know is that the body is larger than it.
    """

    retryable = False

    def __init__(self, message: str = "", *, max_bytes: int | None = None, size: int | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.max_bytes = max_bytes
        self.size = size
