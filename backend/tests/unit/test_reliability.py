"""Offline unit tests for retry, circuit breaker, and fallback.

All tests are offline: no real LLM calls, no network.
Follows the same monkeypatch-everything pattern as test_budget.py.
"""

import pytest

from backend.app.reliability.circuit import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from backend.app.reliability.retry import is_retryable, with_retry


# ---------------------------------------------------------------------------
# retry.py
# ---------------------------------------------------------------------------

class _TimeoutError(Exception):
    pass

class _StatusError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")

# Make _StatusError look like openai.APIStatusError to is_retryable
_StatusError.__name__ = "APIStatusError"


def test_with_retry_succeeds_first_attempt():
    calls = []
    def fn():
        calls.append(1)
        return "ok"
    assert with_retry(fn, attempts=3, base_delay=0) == "ok"
    assert len(calls) == 1


def test_with_retry_retries_on_retryable_error(monkeypatch):
    monkeypatch.setattr("backend.app.reliability.retry.time.sleep", lambda _: None)
    calls = []
    def fn():
        calls.append(1)
        if len(calls) < 3:
            exc = _StatusError(429)
            raise exc
        return "recovered"
    assert with_retry(fn, attempts=3, base_delay=0) == "recovered"
    assert len(calls) == 3


def test_with_retry_raises_after_all_attempts(monkeypatch):
    monkeypatch.setattr("backend.app.reliability.retry.time.sleep", lambda _: None)
    def fn():
        raise _StatusError(503)
    with pytest.raises(_StatusError):
        with_retry(fn, attempts=3, base_delay=0)


def test_with_retry_propagates_non_retryable_immediately():
    calls = []
    def fn():
        calls.append(1)
        raise ValueError("bad input")
    with pytest.raises(ValueError):
        with_retry(fn, attempts=3, base_delay=0)
    assert len(calls) == 1  # raised on first attempt, no retry


def test_is_retryable_timeout():
    class FakeTimeout(Exception):
        pass
    FakeTimeout.__name__ = "APITimeoutError"
    assert is_retryable(FakeTimeout())


def test_is_retryable_429():
    exc = _StatusError(429)
    assert is_retryable(exc)


def test_is_retryable_500():
    exc = _StatusError(500)
    assert is_retryable(exc)


def test_is_not_retryable_400():
    exc = _StatusError(400)
    assert not is_retryable(exc)


def test_is_not_retryable_value_error():
    assert not is_retryable(ValueError("parse error"))


# ---------------------------------------------------------------------------
# circuit.py
# ---------------------------------------------------------------------------

def test_circuit_starts_closed():
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=60)
    assert cb.state == CLOSED
    assert cb.allow_request() is True


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=60)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == OPEN
    assert cb.allow_request() is False


def test_circuit_half_open_after_cooldown(monkeypatch):
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=10)
    cb.record_failure()
    assert cb.state == OPEN

    # Fake time past the cooldown
    start = cb._opened_at
    monkeypatch.setattr(
        "backend.app.reliability.circuit.time.monotonic",
        lambda: start + 15,
    )
    assert cb.allow_request() is True
    assert cb.state == HALF_OPEN


def test_circuit_closes_on_success_after_half_open(monkeypatch):
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=10)
    cb.record_failure()

    start = cb._opened_at
    monkeypatch.setattr(
        "backend.app.reliability.circuit.time.monotonic",
        lambda: start + 15,
    )
    cb.allow_request()  # → HALF_OPEN
    cb.record_success()
    assert cb.state == CLOSED
    assert cb._failures == 0


def test_circuit_reopens_on_failure_in_half_open(monkeypatch):
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=10)
    cb.record_failure()

    start = cb._opened_at
    monkeypatch.setattr(
        "backend.app.reliability.circuit.time.monotonic",
        lambda: start + 15,
    )
    cb.allow_request()  # → HALF_OPEN
    cb.record_failure()  # probe failed → OPEN again
    assert cb.state == OPEN


def test_circuit_reset_on_success():
    cb = CircuitBreaker(failure_threshold=5, cooldown_s=60)
    for _ in range(4):
        cb.record_failure()
    cb.record_success()
    assert cb.state == CLOSED
    assert cb._failures == 0
