"""Tests for retry policy and backoff logic."""

import pytest

from bapp_connectors.core.errors import ProviderError, RateLimitError
from bapp_connectors.core.http.retry import RetryPolicy, execute_with_retry
from bapp_connectors.core.types import BackoffStrategy


def test_exponential_backoff_delays():
    policy = RetryPolicy(backoff=BackoffStrategy.EXPONENTIAL, base_delay=1.0, max_delay=60.0)
    assert policy.compute_delay(0) == 1.0
    assert policy.compute_delay(1) == 2.0
    assert policy.compute_delay(2) == 4.0
    assert policy.compute_delay(3) == 8.0
    assert policy.compute_delay(10) == 60.0  # capped at max_delay


def test_linear_backoff_delays():
    policy = RetryPolicy(backoff=BackoffStrategy.LINEAR, base_delay=2.0, max_delay=20.0)
    assert policy.compute_delay(0) == 2.0
    assert policy.compute_delay(1) == 4.0
    assert policy.compute_delay(9) == 20.0  # capped


def test_no_backoff():
    policy = RetryPolicy(backoff=BackoffStrategy.NONE)
    assert policy.compute_delay(0) == 0.0
    assert policy.compute_delay(5) == 0.0


def test_retryable_status_codes():
    policy = RetryPolicy()
    assert policy.is_retryable_status(429)
    assert policy.is_retryable_status(500)
    assert policy.is_retryable_status(503)
    assert not policy.is_retryable_status(400)
    assert not policy.is_retryable_status(401)
    assert not policy.is_retryable_status(404)
    assert not policy.is_retryable_status(200)


def test_should_retry_respects_max_retries():
    policy = RetryPolicy(max_retries=2)
    err = ProviderError("fail", status_code=500)
    should, _ = policy.should_retry(0, err)
    assert should
    should, _ = policy.should_retry(1, err)
    assert should
    should, _ = policy.should_retry(2, err)
    assert not should


def test_should_retry_non_retryable():
    policy = RetryPolicy(max_retries=3)
    err = ValueError("not retryable")
    should, _ = policy.should_retry(0, err)
    assert not should


def test_should_retry_rate_limit_with_retry_after():
    policy = RetryPolicy(max_retries=3, max_delay=120.0)
    err = RateLimitError("slow", retry_after=45.0)
    should, delay = policy.should_retry(0, err)
    assert should
    assert delay == 45.0


def test_execute_with_retry_succeeds():
    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ProviderError("fail")
        return "success"

    policy = RetryPolicy(max_retries=5, backoff=BackoffStrategy.NONE)
    result = execute_with_retry(flaky, retry_policy=policy)
    assert result == "success"
    assert call_count == 3


def test_execute_with_retry_exhausted():
    def always_fail():
        raise ProviderError("always fail")

    policy = RetryPolicy(max_retries=2, backoff=BackoffStrategy.NONE)
    with pytest.raises(ProviderError):
        execute_with_retry(always_fail, retry_policy=policy)


def test_execute_without_retry():
    def ok():
        return 42

    assert execute_with_retry(ok, retry_policy=None) == 42
