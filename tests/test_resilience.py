"""Tests for atlas/infra/resilience.py — Circuit breaker & retry backoff."""
import time
import pytest
from atlas.infra.resilience import CircuitBreaker, CircuitBreakerOpen, retry_with_backoff


# ── Circuit Breaker Tests ────────────────────────────────────────

def test_circuit_breaker_starts_closed():
    cb = CircuitBreaker(failure_threshold=3)
    assert cb.state == "CLOSED"


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=60)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "OPEN"


def test_circuit_breaker_raises_when_open():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=60)
    cb.record_failure()
    cb.record_failure()
    with pytest.raises(CircuitBreakerOpen):
        with cb:
            pass  # should not reach here


def test_circuit_breaker_resets_on_success():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0


def test_circuit_breaker_half_open_after_timeout():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "OPEN"
    time.sleep(0.15)
    assert cb.state == "HALF_OPEN"


# ── Retry Tests ──────────────────────────────────────────────────

def test_retry_succeeds_on_first_try():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def succeeds():
        nonlocal call_count
        call_count += 1
        return "ok"

    assert succeeds() == "ok"
    assert call_count == 1


def test_retry_succeeds_after_failures():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,))
    def fails_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("transient")
        return "recovered"

    assert fails_twice() == "recovered"
    assert call_count == 3


def test_retry_exhausts_and_raises():
    @retry_with_backoff(max_retries=2, base_delay=0.01, retryable_exceptions=(ValueError,))
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        always_fails()


def test_retry_does_not_retry_non_retryable():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,))
    def non_retryable_error():
        nonlocal call_count
        call_count += 1
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        non_retryable_error()
    assert call_count == 1  # No retry
