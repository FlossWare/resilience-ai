"""Circuit-breaker resilience policy for LLM providers.

Implements the :class:`~resilience_ai.protocol.ResiliencePolicy` protocol
via structural subtyping.  Uses only the standard library -- zero external
dependencies.

The classic three-state circuit breaker:

* **closed** -- requests flow normally; failures are counted.
* **open** -- requests are blocked; after *recovery_timeout* seconds the
  circuit transitions to *half_open*.
* **half_open** -- a single probe request is allowed through.  On success
  the circuit resets to *closed*; on failure it reopens.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from resilience_ai.types import CircuitState


@dataclass
class _ProviderState:
    """Internal mutable state for a single provider."""

    state: str = "closed"
    failure_count: int = 0
    last_failure_at: float = 0.0  # monotonic
    last_failure_wall: float = 0.0  # wall-clock for display
    opened_at: float = 0.0  # monotonic
    opened_at_wall: float = 0.0  # wall-clock for display
    half_open_probe_sent: bool = False


class CircuitBreakerPolicy:
    """Classic three-state circuit breaker.

    Satisfies :class:`~resilience_ai.protocol.ResiliencePolicy` via
    structural subtyping.

    Parameters
    ----------
    failure_threshold:
        Number of consecutive failures before the circuit opens.
    recovery_timeout:
        Seconds to wait in the *open* state before transitioning to
        *half_open*.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._providers: dict[str, _ProviderState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _get(self, provider: str) -> _ProviderState:
        """Return (or create) the internal state for *provider*."""
        if provider not in self._providers:
            self._providers[provider] = _ProviderState()
        return self._providers[provider]

    async def _get_lock(self, provider: str) -> asyncio.Lock:
        async with self._global_lock:
            if provider not in self._locks:
                self._locks[provider] = asyncio.Lock()
            return self._locks[provider]

    # -- ResiliencePolicy protocol -------------------------------------------

    async def should_allow(self, provider: str) -> bool:
        """Return whether requests to *provider* are currently allowed."""
        lock = await self._get_lock(provider)
        async with lock:
            ps = self._get(provider)

            if ps.state == "closed":
                return True

            if ps.state == "open":
                elapsed = time.monotonic() - ps.opened_at
                if elapsed >= self._recovery_timeout:
                    ps.state = "half_open"
                    ps.half_open_probe_sent = True
                    return True
                return False

            # half_open -- allow only one probe at a time
            if not ps.half_open_probe_sent:
                ps.half_open_probe_sent = True
                return True
            return False

    async def record_outcome(
        self, provider: str, *, success: bool, latency_ms: float
    ) -> None:
        """Record the outcome of a request to *provider*."""
        _ = latency_ms  # protocol-mandated; reserved for future latency tracking
        lock = await self._get_lock(provider)
        async with lock:
            ps = self._get(provider)
            now = time.monotonic()

            wall_now = time.time()

            if ps.state == "closed":
                if success:
                    ps.failure_count = 0
                else:
                    ps.failure_count += 1
                    ps.last_failure_at = now
                    ps.last_failure_wall = wall_now
                    if ps.failure_count >= self._failure_threshold:
                        ps.state = "open"
                        ps.opened_at = now
                        ps.opened_at_wall = wall_now

            elif ps.state == "half_open":
                ps.half_open_probe_sent = False
                if success:
                    ps.state = "closed"
                    ps.failure_count = 0
                else:
                    ps.state = "open"
                    ps.failure_count += 1
                    ps.last_failure_at = now
                    ps.last_failure_wall = wall_now
                    ps.opened_at = now
                    ps.opened_at_wall = wall_now

        # In the "open" state we do not expect outcomes (requests are
        # blocked), but if one arrives we simply ignore it.

    async def circuit_state(self, provider: str) -> CircuitState:
        """Return the current :class:`CircuitState` for *provider*."""
        lock = await self._get_lock(provider)
        async with lock:
            ps = self._get(provider)

            last_failure_iso = ""
            if ps.last_failure_wall:
                last_failure_iso = datetime.fromtimestamp(
                    ps.last_failure_wall, tz=timezone.utc
                ).isoformat()

            next_retry_iso = ""
            if ps.state == "open" and ps.opened_at_wall:
                next_retry_ts = ps.opened_at_wall + self._recovery_timeout
                next_retry_iso = datetime.fromtimestamp(
                    next_retry_ts, tz=timezone.utc
                ).isoformat()

            return CircuitState(
                state=ps.state,
                failure_count=ps.failure_count,
                last_failure_at=last_failure_iso,
                next_retry_at=next_retry_iso,
            )
