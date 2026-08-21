"""Tests for resilience-ai package.

Covers circuit breaker, retry, rate limiter, health tracker, and composite
resilience guard.
"""

from __future__ import annotations

import asyncio
import unittest

from resilience_ai import (
    CircuitBreakerPolicy,
    CircuitOpenError,
    CircuitState,
    HealthSnapshot,
    ProviderHealthTracker,
    RateLimiter,
    RetriesExhaustedError,
    ResilientProvider,
    RetryPolicy,
    SimpleRateLimiter,
    async_retry,
    with_circuit_breaker,
    with_rate_limit,
    with_retry,
)
from resilience_ai.protocol import ResiliencePolicy
from resilience_ai.rate_limiter import ProviderLimits, RateLimitInfo


class TestCircuitBreakerPolicy(unittest.TestCase):
    """Tests for the CircuitBreakerPolicy class."""

    def test_initial_state_is_closed(self):
        """A new circuit breaker starts in the closed state."""
        cb = CircuitBreakerPolicy()
        state = asyncio.run(cb.circuit_state("test"))
        self.assertEqual(state.state, "closed")
        self.assertEqual(state.failure_count, 0)

    def test_allows_requests_when_closed(self):
        """Requests are allowed when the circuit is closed."""
        cb = CircuitBreakerPolicy()
        allowed = asyncio.run(cb.should_allow("test"))
        self.assertTrue(allowed)

    def test_opens_after_threshold_failures(self):
        """Circuit opens after reaching the failure threshold."""
        cb = CircuitBreakerPolicy(failure_threshold=3)

        async def run():
            for _ in range(3):
                await cb.record_outcome("test", success=False, latency_ms=100.0)
            return await cb.circuit_state("test")

        state = asyncio.run(run())
        self.assertEqual(state.state, "open")
        self.assertEqual(state.failure_count, 3)

    def test_blocks_requests_when_open(self):
        """Requests are blocked when the circuit is open."""
        cb = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout=9999.0)

        async def run():
            await cb.record_outcome("test", success=False, latency_ms=0.0)
            await cb.record_outcome("test", success=False, latency_ms=0.0)
            return await cb.should_allow("test")

        allowed = asyncio.run(run())
        self.assertFalse(allowed)

    def test_success_resets_failure_count(self):
        """A success in the closed state resets the failure counter."""
        cb = CircuitBreakerPolicy(failure_threshold=5)

        async def run():
            await cb.record_outcome("test", success=False, latency_ms=0.0)
            await cb.record_outcome("test", success=False, latency_ms=0.0)
            await cb.record_outcome("test", success=True, latency_ms=0.0)
            return await cb.circuit_state("test")

        state = asyncio.run(run())
        self.assertEqual(state.state, "closed")
        self.assertEqual(state.failure_count, 0)

    def test_half_open_after_recovery_timeout(self):
        """Circuit transitions to half_open after recovery_timeout."""
        cb = CircuitBreakerPolicy(failure_threshold=1, recovery_timeout=0.0)

        async def run():
            await cb.record_outcome("test", success=False, latency_ms=0.0)
            # recovery_timeout=0 so it should immediately transition
            return await cb.should_allow("test")

        allowed = asyncio.run(run())
        self.assertTrue(allowed)

    def test_half_open_success_closes_circuit(self):
        """A success in half_open state resets circuit to closed."""
        cb = CircuitBreakerPolicy(failure_threshold=1, recovery_timeout=0.0)

        async def run():
            await cb.record_outcome("test", success=False, latency_ms=0.0)
            await cb.should_allow("test")  # triggers half_open
            await cb.record_outcome("test", success=True, latency_ms=0.0)
            return await cb.circuit_state("test")

        state = asyncio.run(run())
        self.assertEqual(state.state, "closed")
        self.assertEqual(state.failure_count, 0)

    def test_satisfies_resilience_protocol(self):
        """CircuitBreakerPolicy satisfies the ResiliencePolicy protocol."""
        cb = CircuitBreakerPolicy()
        self.assertIsInstance(cb, ResiliencePolicy)

    def test_circuit_state_returns_dataclass(self):
        """circuit_state returns a CircuitState dataclass."""
        cb = CircuitBreakerPolicy()
        state = asyncio.run(cb.circuit_state("test"))
        self.assertIsInstance(state, CircuitState)


class TestRetryPolicy(unittest.TestCase):
    """Tests for the RetryPolicy class."""

    def test_default_retries_all_exceptions(self):
        """By default all exceptions are retryable."""
        policy = RetryPolicy()
        self.assertTrue(policy.is_retryable(ValueError("test")))
        self.assertTrue(policy.is_retryable(RuntimeError("test")))

    def test_no_retry_on_takes_precedence(self):
        """no_retry_on exceptions are never retried."""
        policy = RetryPolicy(no_retry_on=(ValueError,))
        self.assertFalse(policy.is_retryable(ValueError("test")))
        self.assertTrue(policy.is_retryable(RuntimeError("test")))

    def test_retry_on_restricts_retryable(self):
        """When retry_on is set, only listed types are retried."""
        policy = RetryPolicy(retry_on=(ValueError,))
        self.assertTrue(policy.is_retryable(ValueError("test")))
        self.assertFalse(policy.is_retryable(RuntimeError("test")))

    def test_delay_increases_with_attempt(self):
        """Delay should increase with attempt number (exponential backoff)."""
        import random as _random

        rng = _random.Random(42)
        policy = RetryPolicy(backoff_base=2.0, jitter_range=0.0, _rng=rng)
        d0 = policy.delay(0)
        d1 = policy.delay(1)
        d2 = policy.delay(2)
        self.assertLess(d0, d1)
        self.assertLess(d1, d2)

    def test_delay_capped(self):
        """Delay must not exceed backoff_cap."""
        import random as _random

        rng = _random.Random(42)
        policy = RetryPolicy(backoff_base=2.0, backoff_cap=5.0, jitter_range=0.0, _rng=rng)
        delay = policy.delay(100)
        self.assertLessEqual(delay, 5.0)


class TestAsyncRetry(unittest.TestCase):
    """Tests for the async_retry decorator."""

    def test_successful_call_returns_value(self):
        """Successful calls return normally."""
        policy = RetryPolicy(max_retries=3)

        @async_retry(policy)
        async def ok():
            return 42

        result = asyncio.run(ok())
        self.assertEqual(result, 42)

    def test_retries_on_failure_then_succeeds(self):
        """Retries on failure, then succeeds."""
        call_count = 0
        policy = RetryPolicy(max_retries=3, backoff_base=0.01, backoff_cap=0.01, jitter_range=0.0)

        @async_retry(policy)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary")
            return "ok"

        result = asyncio.run(flaky())
        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 3)

    def test_raises_retries_exhausted(self):
        """Raises RetriesExhaustedError when all retries fail."""
        policy = RetryPolicy(max_retries=2, backoff_base=0.01, backoff_cap=0.01, jitter_range=0.0)

        @async_retry(policy)
        async def always_fails():
            raise ValueError("permanent")

        with self.assertRaises(RetriesExhaustedError) as ctx:
            asyncio.run(always_fails())
        self.assertEqual(ctx.exception.attempts, 3)

    def test_circuit_open_prevents_call(self):
        """CircuitOpenError raised when circuit is open."""
        cb = CircuitBreakerPolicy(failure_threshold=1, recovery_timeout=9999.0)
        policy = RetryPolicy(max_retries=0)

        @async_retry(policy, resilience=cb, provider="test")
        async def guarded():
            return "ok"

        async def run():
            await cb.record_outcome("test", success=False, latency_ms=0.0)
            return await guarded()

        with self.assertRaises(CircuitOpenError):
            asyncio.run(run())

    def test_non_retryable_exception_raised_immediately(self):
        """Non-retryable exceptions are raised without retry."""
        call_count = 0
        policy = RetryPolicy(max_retries=5, no_retry_on=(TypeError,), backoff_base=0.01)

        @async_retry(policy)
        async def fails_with_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("fatal")

        with self.assertRaises(TypeError):
            asyncio.run(fails_with_type_error())
        self.assertEqual(call_count, 1)


class TestRateLimiter(unittest.TestCase):
    """Tests for the async RateLimiter class."""

    def test_acquire_does_not_block_initially(self):
        """Acquire returns immediately when bucket is full."""
        rl = RateLimiter()

        async def run():
            waited = await rl.acquire("test")
            return waited

        waited = asyncio.run(run())
        self.assertEqual(waited, 0.0)

    def test_parse_headers_extracts_remaining(self):
        """parse_headers extracts X-RateLimit-Remaining."""
        info = RateLimiter.parse_headers({"X-RateLimit-Remaining": "42"})
        self.assertEqual(info.remaining, 42)

    def test_parse_headers_extracts_retry_after(self):
        """parse_headers extracts Retry-After."""
        info = RateLimiter.parse_headers({"Retry-After": "30.0"})
        self.assertEqual(info.retry_after, 30.0)

    def test_parse_headers_handles_invalid_values(self):
        """parse_headers ignores non-numeric header values."""
        info = RateLimiter.parse_headers({"X-RateLimit-Remaining": "invalid"})
        self.assertIsNone(info.remaining)


class TestProviderHealthTracker(unittest.TestCase):
    """Tests for the ProviderHealthTracker class."""

    def test_empty_snapshot(self):
        """Snapshot for an unknown provider has zero totals."""
        tracker = ProviderHealthTracker()
        snap = tracker.snapshot("unknown")
        self.assertEqual(snap.total_requests, 0)
        self.assertEqual(snap.error_rate, 0.0)
        self.assertIsInstance(snap, HealthSnapshot)

    def test_records_and_computes_error_rate(self):
        """Error rate reflects the proportion of failures."""
        tracker = ProviderHealthTracker()
        tracker.record("test", success=True, latency_ms=100.0)
        tracker.record("test", success=False, latency_ms=200.0)
        snap = tracker.snapshot("test")
        self.assertEqual(snap.total_requests, 2)
        self.assertAlmostEqual(snap.error_rate, 0.5)

    def test_parses_rate_limit_headers(self):
        """Rate-limit headers are parsed and stored in snapshot."""
        tracker = ProviderHealthTracker()
        tracker.record(
            "test",
            success=True,
            latency_ms=50.0,
            headers={"X-RateLimit-Remaining": "10", "X-RateLimit-Reset": "1700000000"},
        )
        snap = tracker.snapshot("test")
        self.assertEqual(snap.rate_limit_remaining, 10)
        self.assertEqual(snap.rate_limit_reset_at, 1700000000.0)


class TestSimpleRateLimiter(unittest.TestCase):
    """Tests for the SimpleRateLimiter class."""

    def test_acquire_returns_true_initially(self):
        """First acquire should succeed."""
        rl = SimpleRateLimiter(default_rpm=60)
        self.assertTrue(rl.acquire("test"))

    def test_exhausting_tokens(self):
        """Acquiring more than capacity fails."""
        rl = SimpleRateLimiter(default_rpm=2)
        self.assertTrue(rl.acquire("test"))
        self.assertTrue(rl.acquire("test"))
        self.assertFalse(rl.acquire("test"))


class TestResilientProvider(unittest.TestCase):
    """Tests for the ResilientProvider composite guard."""

    def test_allows_initially(self):
        """ResilientProvider allows requests for a fresh provider."""
        rp = ResilientProvider()
        allowed = asyncio.run(rp.should_allow("test"))
        self.assertTrue(allowed)

    def test_satisfies_resilience_protocol(self):
        """ResilientProvider satisfies the ResiliencePolicy protocol."""
        rp = ResilientProvider()
        self.assertIsInstance(rp, ResiliencePolicy)

    def test_record_outcome_propagates(self):
        """record_outcome updates both circuit breaker and health tracker."""

        async def run():
            rp = ResilientProvider()
            await rp.record_outcome("test", success=True, latency_ms=50.0)
            snap = rp.health_tracker.snapshot("test")
            state = await rp.circuit_state("test")
            return snap, state

        snap, state = asyncio.run(run())
        self.assertEqual(snap.total_requests, 1)
        self.assertEqual(state.state, "closed")


class TestWithRetryDecorator(unittest.TestCase):
    """Tests for the @with_retry convenience decorator."""

    def test_success(self):
        """Decorated function returns normally on success."""

        @with_retry(attempts=3, backoff=0.01, jitter=0.0)
        async def ok():
            return "hello"

        self.assertEqual(asyncio.run(ok()), "hello")

    def test_retries_then_succeeds(self):
        """Decorated function retries and eventually succeeds."""
        call_count = 0

        @with_retry(attempts=3, backoff=0.01, backoff_cap=0.01, jitter=0.0)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("temp")
            return "ok"

        self.assertEqual(asyncio.run(flaky()), "ok")
        self.assertEqual(call_count, 2)

    def test_exhausted(self):
        """Raises RetriesExhaustedError when all attempts fail."""

        @with_retry(attempts=2, backoff=0.01, backoff_cap=0.01, jitter=0.0)
        async def always_fails():
            raise RuntimeError("permanent")

        with self.assertRaises(RetriesExhaustedError):
            asyncio.run(always_fails())


class TestWithCircuitBreakerDecorator(unittest.TestCase):
    """Tests for the @with_circuit_breaker convenience decorator."""

    def test_success(self):
        """Decorated function works normally."""

        @with_circuit_breaker(max_failures=3)
        async def ok():
            return 42

        self.assertEqual(asyncio.run(ok()), 42)

    def test_opens_after_failures(self):
        """Circuit opens after max_failures consecutive failures."""

        @with_circuit_breaker(max_failures=2, recovery_timeout=9999.0)
        async def fail():
            raise ValueError("boom")

        # Trigger 2 failures to open the circuit
        for _ in range(2):
            with self.assertRaises(ValueError):
                asyncio.run(fail())

        # Now circuit should be open
        with self.assertRaises(CircuitOpenError):
            asyncio.run(fail())


class TestWithRateLimitDecorator(unittest.TestCase):
    """Tests for the @with_rate_limit convenience decorator."""

    def test_allows_call(self):
        """Decorated function executes when under rate limit."""

        @with_rate_limit(requests_per_second=100)
        async def ok():
            return "fast"

        self.assertEqual(asyncio.run(ok()), "fast")


class TestNoLoomAiImports(unittest.TestCase):
    """Verify the package has zero loom_ai imports."""

    def test_no_loom_ai_imports(self):
        """Scan all package files for 'from loom_ai' or 'import loom_ai'."""
        import pathlib

        pkg_dir = pathlib.Path(__file__).resolve().parent.parent / "resilience_ai"
        for py_file in pkg_dir.rglob("*.py"):
            content = py_file.read_text()
            self.assertNotIn(
                "from loom_ai",
                content,
                f"{py_file.name} contains 'from loom_ai' import",
            )
            self.assertNotIn(
                "import loom_ai",
                content,
                f"{py_file.name} contains 'import loom_ai' import",
            )


if __name__ == "__main__":
    unittest.main()
