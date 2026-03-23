"""Tests for the token-bucket rate limiter."""

import time

import pytest

from bapp_connectors.core.http.rate_limit import RateLimiter


def test_acquire_within_burst():
    limiter = RateLimiter(requests_per_second=10, burst=5)
    for _ in range(5):
        assert limiter.acquire() is True


def test_acquire_exhausted_without_timeout():
    limiter = RateLimiter(requests_per_second=1, burst=1)
    assert limiter.acquire() is True
    assert limiter.acquire() is False  # no timeout, immediately false


def test_acquire_with_timeout():
    limiter = RateLimiter(requests_per_second=10, burst=1)
    assert limiter.acquire() is True
    start = time.monotonic()
    assert limiter.acquire(timeout=1.0) is True
    elapsed = time.monotonic() - start
    assert elapsed < 0.5  # should refill quickly at 10 rps


def test_wait_blocks():
    limiter = RateLimiter(requests_per_second=10, burst=1)
    limiter.acquire()  # consume the token
    start = time.monotonic()
    limiter.wait()  # should block until refill
    elapsed = time.monotonic() - start
    assert elapsed < 0.5


def test_invalid_rate():
    with pytest.raises(ValueError):
        RateLimiter(requests_per_second=0)
    with pytest.raises(ValueError):
        RateLimiter(requests_per_second=-1)
