"""Convenience decorators for resilience patterns (ADR-0006).

Provides thin wrappers around the core classes for quick opt-in:

* :func:`with_retry` -- retry with exponential backoff
* :func:`with_circuit_breaker` -- per-provider circuit breaker
* :func:`with_rate_limit` -- token-bucket rate limiting

All decorators are explicit opt-in (ADR-0001) -- importing this module
does nothing until a decorator is applied to a function.

Uses only the standard library -- zero external dependencies (ADR-0008).
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any

from resilience_ai.rate_limiter import ProviderLimits, RateLimiter
from resilience_ai.resilience import CircuitBreakerPolicy
from resilience_ai.retry import RetryPolicy, async_retry


def with_retry(
    *,
    attempts: int = 3,
    backoff: float = 2.0,
    backoff_cap: float = 10.0,
    jitter: float = 1.0,
    retry_on: tuple[type[Exception], ...] = (),
    no_retry_on: tuple[type[Exception], ...] = (),
) -> Callable:
    """Decorator: retry an async function with exponential backoff.

    Parameters
    ----------
    attempts:
        Total number of attempts (first call + retries).
    backoff:
        Base for exponential backoff.
    backoff_cap:
        Maximum delay in seconds between retries.
    jitter:
        Upper bound for random jitter added to delay.
    retry_on:
        Exception types to retry.  Empty = retry all.
    no_retry_on:
        Exception types to never retry (takes precedence).

    Example
    -------
    ::

        @with_retry(attempts=3, backoff=1.0)
        async def call_api():
            ...
    """
    policy = RetryPolicy(
        max_retries=max(0, attempts - 1),
        backoff_base=backoff,
        backoff_cap=backoff_cap,
        jitter_range=jitter,
        retry_on=retry_on,
        no_retry_on=no_retry_on,
    )
    return async_retry(policy)


def with_circuit_breaker(
    *,
    max_failures: int = 5,
    recovery_timeout: float = 60.0,
    provider: str = "default",
) -> Callable:
    """Decorator: guard an async function with a circuit breaker.

    Creates a dedicated :class:`CircuitBreakerPolicy` for the decorated
    function.  The circuit opens after *max_failures* consecutive
    failures and transitions to half-open after *recovery_timeout*
    seconds.

    Parameters
    ----------
    max_failures:
        Failures before opening the circuit.
    recovery_timeout:
        Seconds before probing again.
    provider:
        Provider name for circuit-breaker tracking.

    Example
    -------
    ::

        @with_circuit_breaker(max_failures=5)
        async def call_llm():
            ...
    """
    cb = CircuitBreakerPolicy(
        failure_threshold=max_failures,
        recovery_timeout=recovery_timeout,
    )

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            from resilience_ai.retry import CircuitOpenError

            if not await cb.should_allow(provider):
                raise CircuitOpenError(
                    f"Circuit breaker open for provider {provider!r}"
                )

            t0 = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                latency = (time.monotonic() - t0) * 1000
                await cb.record_outcome(
                    provider, success=True, latency_ms=latency
                )
                return result
            except Exception:
                latency = (time.monotonic() - t0) * 1000
                await cb.record_outcome(
                    provider, success=False, latency_ms=latency
                )
                raise

        wrapper._circuit_breaker = cb  # type: ignore[attr-defined]
        return wrapper

    return decorator


def with_rate_limit(
    *,
    requests_per_second: float = 1.0,
    provider: str = "default",
) -> Callable:
    """Decorator: throttle an async function with a token-bucket rate limiter.

    Creates a per-decorator :class:`RateLimiter` instance.  The function
    will ``await`` until a request slot is available.

    Parameters
    ----------
    requests_per_second:
        Maximum sustained request rate.
    provider:
        Provider name for bucket lookup.

    Example
    -------
    ::

        @with_rate_limit(requests_per_second=10)
        async def call_api():
            ...
    """
    rpm = requests_per_second * 60.0
    limiter = RateLimiter(
        default_limits=ProviderLimits(requests_per_minute=rpm),
    )

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            await limiter.acquire(provider)
            return await fn(*args, **kwargs)

        wrapper._rate_limiter = limiter  # type: ignore[attr-defined]
        return wrapper

    return decorator
