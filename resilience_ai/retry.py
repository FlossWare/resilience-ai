"""Reusable async retry with exponential backoff and circuit-breaker integration.

Provides :class:`RetryPolicy` (configuration) and :func:`async_retry`
(decorator factory) for standardised retry behaviour across all backends.
Uses only the standard library -- zero external dependencies.

Failure classification
----------------------
By default every :class:`Exception` is retryable.  Pass *retry_on* to
restrict retries to specific exception types and *no_retry_on* to
short-circuit for known-fatal errors.

Circuit-breaker integration
---------------------------
When an optional :class:`~resilience_ai.resilience.CircuitBreakerPolicy`
(or any :class:`~resilience_ai.protocol.ResiliencePolicy` implementor) is
provided, the decorator will:

1. Check ``should_allow`` before each attempt.
2. Record success/failure via ``record_outcome`` after each attempt.
3. Skip the call entirely when the circuit is open, raising
   :class:`CircuitOpenError`.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from resilience_ai.protocol import ResiliencePolicy

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    """Raised when a call is blocked by an open circuit breaker."""


class RetriesExhaustedError(RuntimeError):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, message: str, attempts: int, last_exception: Exception) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_exception = last_exception


@dataclass
class RetryPolicy:
    """Configuration for retry behaviour.

    Parameters
    ----------
    max_retries:
        Maximum number of retries (total attempts = max_retries + 1).
    backoff_base:
        Base for exponential backoff (delay = backoff_base ** attempt).
    backoff_cap:
        Maximum delay in seconds between retries.
    jitter_range:
        Upper bound for uniform random jitter added to the delay.
    retry_on:
        Tuple of exception types that should trigger a retry.  When empty,
        all :class:`Exception` subclasses are retried (unless excluded by
        *no_retry_on*).
    no_retry_on:
        Tuple of exception types that should never be retried.  Takes
        precedence over *retry_on*.
    """

    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_cap: float = 10.0
    jitter_range: float = 1.0
    retry_on: tuple[type[Exception], ...] = ()
    no_retry_on: tuple[type[Exception], ...] = ()
    _rng: random.Random = field(default_factory=random.Random)  # noqa: S311

    def is_retryable(self, exc: Exception) -> bool:
        """Return whether *exc* should trigger a retry."""
        if self.no_retry_on and isinstance(exc, self.no_retry_on):
            return False
        if self.retry_on:
            return isinstance(exc, self.retry_on)
        return True

    def delay(self, attempt: int) -> float:
        """Return the backoff delay in seconds for the given *attempt* (0-based)."""
        raw = self.backoff_base**attempt + self._rng.uniform(0, self.jitter_range)
        return min(raw, self.backoff_cap)


async def _record_outcome(
    resilience: ResiliencePolicy | None,
    provider: str,
    t0: float,
    *,
    success: bool,
) -> None:
    if resilience is not None:
        elapsed_ms = (time.monotonic() - t0) * 1000
        await resilience.record_outcome(
            provider, success=success, latency_ms=elapsed_ms
        )


def async_retry(
    policy: RetryPolicy | None = None,
    *,
    resilience: ResiliencePolicy | None = None,
    provider: str = "",
) -> Callable:
    """Decorator factory for async functions with retry and circuit-breaker support.

    Parameters
    ----------
    policy:
        Retry configuration.  Defaults to a :class:`RetryPolicy` with
        default settings when ``None``.
    resilience:
        Optional circuit-breaker / resilience policy.  When provided the
        decorator checks ``should_allow`` before each attempt and records
        outcomes via ``record_outcome``.
    provider:
        Provider name passed to the resilience policy.  Only meaningful
        when *resilience* is not ``None``.
    """
    if policy is None:
        policy = RetryPolicy()

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if resilience is not None and not await resilience.should_allow(provider):
                raise CircuitOpenError(
                    f"Circuit breaker open for provider {provider!r}"
                )

            last_exc: Exception | None = None
            t0 = time.monotonic()

            for attempt in range(policy.max_retries + 1):
                try:
                    result = await fn(*args, **kwargs)
                    await _record_outcome(resilience, provider, t0, success=True)
                    return result
                except Exception as exc:
                    last_exc = exc

                    if not policy.is_retryable(exc):
                        await _record_outcome(resilience, provider, t0, success=False)
                        raise

                    logger.warning(
                        "%s failed (attempt %d/%d): %s",
                        fn.__qualname__,
                        attempt + 1,
                        policy.max_retries + 1,
                        exc,
                    )

                    if attempt < policy.max_retries:
                        await asyncio.sleep(policy.delay(attempt))
                        allowed = resilience is None or (
                            await resilience.should_allow(provider)
                        )
                        if not allowed:
                            raise CircuitOpenError(
                                f"Circuit breaker open for provider {provider!r}"
                            )

            await _record_outcome(resilience, provider, t0, success=False)

            assert last_exc is not None
            raise RetriesExhaustedError(
                f"{fn.__qualname__} failed after {policy.max_retries + 1} attempts",
                attempts=policy.max_retries + 1,
                last_exception=last_exc,
            ) from last_exc

        return wrapper

    return decorator
