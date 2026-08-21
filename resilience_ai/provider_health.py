"""Provider health tracking, rate limiting, and resilience composition.

Extends the circuit-breaker pattern from :mod:`resilience_ai.resilience` with:

* **ProviderHealthTracker** -- rolling-window response-time and error-rate
  monitoring with rate-limit header parsing.
* **SimpleRateLimiter** -- per-provider token-bucket rate limiting that
  respects both configured limits and limits learned from HTTP response
  headers.
* **ResilientProvider** -- composite guard that combines health tracking,
  rate limiting, and circuit breaking into a single ``should_allow`` /
  ``record_outcome`` surface.

All classes use only the standard library -- zero external dependencies.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from resilience_ai.resilience import CircuitBreakerPolicy
from resilience_ai.types import CircuitState

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class HealthSnapshot:
    """Point-in-time health summary for a single provider."""

    provider: str
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    error_rate: float = 0.0
    total_requests: int = 0
    rate_limit_remaining: int | None = None
    rate_limit_reset_at: float | None = None


@dataclass
class _RequestRecord:
    """Internal record for a single request outcome."""

    timestamp: float
    latency_ms: float
    success: bool


@dataclass
class _ProviderMetrics:
    """Internal rolling-window metrics for a provider."""

    window: deque[_RequestRecord] = field(default_factory=deque)
    rate_limit_remaining: int | None = None
    rate_limit_reset_at: float | None = None


# ---------------------------------------------------------------------------
# ProviderHealthTracker
# ---------------------------------------------------------------------------


class ProviderHealthTracker:
    """Rolling-window health monitor for LLM providers.

    Tracks response latencies and error rates over a configurable time
    window, and parses rate-limit headers from provider responses.

    Parameters
    ----------
    window_seconds:
        Length of the sliding observation window in seconds.
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        self._window_seconds = window_seconds
        self._providers: dict[str, _ProviderMetrics] = {}

    def _get(self, provider: str) -> _ProviderMetrics:
        if provider not in self._providers:
            self._providers[provider] = _ProviderMetrics()
        return self._providers[provider]

    def _prune(self, metrics: _ProviderMetrics) -> None:
        """Remove records older than the observation window."""
        cutoff = time.monotonic() - self._window_seconds
        while metrics.window and metrics.window[0].timestamp < cutoff:
            metrics.window.popleft()

    def record(
        self,
        provider: str,
        *,
        success: bool,
        latency_ms: float,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Record a request outcome and optionally parse rate-limit headers.

        Recognised headers (case-insensitive lookup):

        * ``x-ratelimit-remaining`` -- remaining requests in the window
        * ``x-ratelimit-reset`` -- Unix timestamp when the window resets
        """
        metrics = self._get(provider)
        metrics.window.append(
            _RequestRecord(
                timestamp=time.monotonic(),
                latency_ms=latency_ms,
                success=success,
            )
        )
        self._prune(metrics)

        if headers:
            lower = {k.lower(): v for k, v in headers.items()}
            if "x-ratelimit-remaining" in lower:
                try:
                    metrics.rate_limit_remaining = int(lower["x-ratelimit-remaining"])
                except (ValueError, TypeError):
                    pass
            if "x-ratelimit-reset" in lower:
                try:
                    metrics.rate_limit_reset_at = float(lower["x-ratelimit-reset"])
                except (ValueError, TypeError):
                    pass

    def snapshot(self, provider: str) -> HealthSnapshot:
        """Return a :class:`HealthSnapshot` for *provider*."""
        metrics = self._get(provider)
        self._prune(metrics)

        records = list(metrics.window)
        total = len(records)

        if total == 0:
            return HealthSnapshot(
                provider=provider,
                rate_limit_remaining=metrics.rate_limit_remaining,
                rate_limit_reset_at=metrics.rate_limit_reset_at,
            )

        latencies = sorted(r.latency_ms for r in records)
        errors = sum(1 for r in records if not r.success)
        p95_idx = min(len(latencies) - 1, int(len(latencies) * 0.95))

        return HealthSnapshot(
            provider=provider,
            avg_latency_ms=sum(latencies) / total,
            p95_latency_ms=latencies[p95_idx],
            error_rate=errors / total,
            total_requests=total,
            rate_limit_remaining=metrics.rate_limit_remaining,
            rate_limit_reset_at=metrics.rate_limit_reset_at,
        )


# ---------------------------------------------------------------------------
# SimpleRateLimiter
# ---------------------------------------------------------------------------


class SimpleRateLimiter:
    """Token-bucket rate limiter for per-provider request throttling.

    Each provider gets an independent bucket that refills at a steady rate.
    Callers invoke :meth:`acquire` before sending a request; it returns
    ``True`` if the request is allowed, ``False`` otherwise.

    The limiter also accepts rate-limit headers from provider responses via
    :meth:`update_from_headers`, which can *reduce* the effective limit
    when the provider signals its own constraints.

    Parameters
    ----------
    default_rpm:
        Default requests-per-minute for providers without explicit config.
    """

    def __init__(self, default_rpm: int = 60) -> None:
        self._default_rpm = default_rpm
        self._configs: dict[str, int] = {}  # provider -> rpm
        self._tokens: dict[str, float] = {}
        self._last_refill: dict[str, float] = {}

    def configure(self, provider: str, *, rpm: int) -> None:
        """Set or update the rate limit for *provider*."""
        self._configs[provider] = rpm

    def _rpm(self, provider: str) -> int:
        return self._configs.get(provider, self._default_rpm)

    def _refill(self, provider: str) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        rpm = self._rpm(provider)
        if provider not in self._last_refill:
            self._tokens[provider] = float(rpm)
            self._last_refill[provider] = now
            return

        elapsed = now - self._last_refill[provider]
        refill = elapsed * (rpm / 60.0)
        self._tokens[provider] = min(
            float(rpm), self._tokens.get(provider, 0.0) + refill
        )
        self._last_refill[provider] = now

    def acquire(self, provider: str) -> bool:
        """Try to consume one token.  Return ``True`` if allowed."""
        self._refill(provider)
        if self._tokens.get(provider, 0.0) >= 1.0:
            self._tokens[provider] -= 1.0
            return True
        return False

    def update_from_headers(self, provider: str, headers: dict[str, str]) -> None:
        """Adjust internal state from provider rate-limit response headers.

        If ``x-ratelimit-remaining`` is ``0`` and ``x-ratelimit-reset`` is
        in the future, the bucket is drained so that :meth:`acquire`
        returns ``False`` until the reset time passes and tokens refill.
        """
        lower = {k.lower(): v for k, v in headers.items()}
        remaining = lower.get("x-ratelimit-remaining")
        reset_at = lower.get("x-ratelimit-reset")

        if remaining is not None:
            try:
                remaining_int = int(remaining)
            except (ValueError, TypeError):
                return
            if remaining_int == 0:
                # Drain the bucket
                self._tokens[provider] = 0.0
                if reset_at is not None:
                    try:
                        self._last_refill[provider] = float(reset_at)
                    except (ValueError, TypeError):
                        pass


# ---------------------------------------------------------------------------
# ResilientProvider -- composite guard
# ---------------------------------------------------------------------------


class ResilientProvider:
    """Composite resilience guard combining health, rate limiting, and
    circuit breaking.

    Wraps a :class:`CircuitBreakerPolicy`, a :class:`ProviderHealthTracker`,
    and a :class:`SimpleRateLimiter` behind a unified async interface that
    satisfies the :class:`~resilience_ai.protocol.ResiliencePolicy`
    protocol.

    Parameters
    ----------
    circuit_breaker:
        An existing :class:`CircuitBreakerPolicy` instance, or ``None`` to
        create one with default settings.
    health_tracker:
        An existing :class:`ProviderHealthTracker`, or ``None`` to create
        one with a 5-minute window.
    rate_limiter:
        An existing :class:`SimpleRateLimiter`, or ``None`` to create one
        with a default of 60 RPM.
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreakerPolicy | None = None,
        health_tracker: ProviderHealthTracker | None = None,
        rate_limiter: SimpleRateLimiter | None = None,
    ) -> None:
        self._cb = circuit_breaker or CircuitBreakerPolicy()
        self._health = health_tracker or ProviderHealthTracker()
        self._rl = rate_limiter or SimpleRateLimiter()

    @property
    def circuit_breaker(self) -> CircuitBreakerPolicy:
        """The underlying circuit breaker."""
        return self._cb

    @property
    def health_tracker(self) -> ProviderHealthTracker:
        """The underlying health tracker."""
        return self._health

    @property
    def rate_limiter(self) -> SimpleRateLimiter:
        """The underlying rate limiter."""
        return self._rl

    # -- ResiliencePolicy protocol ---------------------------------------------

    async def should_allow(self, provider: str) -> bool:
        """Return ``True`` only if the circuit breaker allows the request
        *and* the rate limiter has tokens available."""
        cb_ok = await self._cb.should_allow(provider)
        if not cb_ok:
            return False
        return self._rl.acquire(provider)

    async def record_outcome(
        self,
        provider: str,
        *,
        success: bool,
        latency_ms: float,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Record request outcome across all three subsystems."""
        await self._cb.record_outcome(provider, success=success, latency_ms=latency_ms)
        self._health.record(
            provider,
            success=success,
            latency_ms=latency_ms,
            headers=headers,
        )
        if headers:
            self._rl.update_from_headers(provider, headers)

    async def circuit_state(self, provider: str) -> CircuitState:
        """Delegate to the underlying circuit breaker."""
        return await self._cb.circuit_state(provider)
