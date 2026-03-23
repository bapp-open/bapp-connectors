"""
Retry policies with exponential backoff and retryable error classification.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from requests.exceptions import ConnectionError, ReadTimeout, Timeout

from bapp_connectors.core.errors import ConnectorError, RateLimitError
from bapp_connectors.core.types import BackoffStrategy

logger = logging.getLogger(__name__)

# Default status codes that are safe to retry
DEFAULT_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404}
DEFAULT_RETRYABLE_EXCEPTIONS = (ConnectionError, Timeout, ReadTimeout)


@dataclass
class RetryPolicy:
    """Configurable retry policy with backoff."""

    max_retries: int = 3
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    base_delay: float = 1.0
    max_delay: float = 60.0
    retryable_status_codes: set[int] = field(default_factory=lambda: set(DEFAULT_RETRYABLE_STATUS_CODES))
    non_retryable_status_codes: set[int] = field(default_factory=lambda: set(DEFAULT_NON_RETRYABLE_STATUS_CODES))
    retryable_exceptions: tuple = DEFAULT_RETRYABLE_EXCEPTIONS

    def compute_delay(self, attempt: int) -> float:
        """Compute delay for the given attempt number (0-based)."""
        if self.backoff == BackoffStrategy.NONE:
            return 0.0
        if self.backoff == BackoffStrategy.LINEAR:
            delay = self.base_delay * (attempt + 1)
        elif self.backoff == BackoffStrategy.EXPONENTIAL:
            delay = self.base_delay * (2**attempt)
        else:
            delay = self.base_delay

        return min(delay, self.max_delay)

    def is_retryable_status(self, status_code: int) -> bool:
        """Check if a status code is retryable."""
        if status_code in self.non_retryable_status_codes:
            return False
        return status_code in self.retryable_status_codes

    def is_retryable_exception(self, exc: Exception) -> bool:
        """Check if an exception is retryable."""
        if isinstance(exc, ConnectorError):
            return exc.retryable
        return isinstance(exc, self.retryable_exceptions)

    def should_retry(self, attempt: int, error: Exception) -> tuple[bool, float]:
        """
        Determine if we should retry and how long to wait.

        Returns (should_retry, delay_seconds).
        """
        if attempt >= self.max_retries:
            return False, 0.0

        if isinstance(error, RateLimitError) and error.retry_after:
            return True, min(error.retry_after, self.max_delay)

        if not self.is_retryable_exception(error):
            return False, 0.0

        delay = self.compute_delay(attempt)
        return True, delay


def execute_with_retry(func, retry_policy: RetryPolicy | None = None, **kwargs):
    """
    Execute a function with retry logic.

    Args:
        func: Callable to execute.
        retry_policy: RetryPolicy instance. If None, no retries.
        **kwargs: Passed to func.
    """
    if retry_policy is None:
        return func(**kwargs)

    last_error = None
    for attempt in range(retry_policy.max_retries + 1):
        try:
            return func(**kwargs)
        except Exception as exc:
            last_error = exc
            should_retry, delay = retry_policy.should_retry(attempt, exc)
            if not should_retry:
                raise
            logger.warning(
                "Retry attempt %d/%d after %.1fs for %s: %s",
                attempt + 1,
                retry_policy.max_retries,
                delay,
                func.__name__ if hasattr(func, "__name__") else str(func),
                exc,
            )
            if delay > 0:
                time.sleep(delay)

    raise last_error  # type: ignore[misc]
