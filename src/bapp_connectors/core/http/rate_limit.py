"""
Token-bucket rate limiter, scoped per provider instance.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """
    Thread-safe token-bucket rate limiter.

    Args:
        requests_per_second: Sustained request rate.
        burst: Maximum tokens (burst capacity).
    """

    def __init__(self, requests_per_second: float, burst: int = 1):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.rate = requests_per_second
        self.burst = max(burst, 1)
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self, timeout: float | None = None) -> bool:
        """
        Try to acquire a token. Returns True if acquired within timeout.

        Args:
            timeout: Max seconds to wait. None = don't wait, just check.
        """
        deadline = time.monotonic() + timeout if timeout is not None else None

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

            if deadline is None:
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            # Sleep until we'd have a token, but no longer than remaining timeout
            wait = min(1.0 / self.rate, remaining)
            time.sleep(wait)

    def wait(self) -> None:
        """Block until a token is available (no timeout)."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(1.0 / self.rate)
