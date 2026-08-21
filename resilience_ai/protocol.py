"""Resilience policy protocol definition.

Defines the structural interface that all resilience policies must satisfy.
Uses only the standard library -- zero external dependencies.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from resilience_ai.types import CircuitState


@runtime_checkable
class ResiliencePolicy(Protocol):
    """Structural protocol for resilience policies.

    Any class that implements :meth:`should_allow`, :meth:`record_outcome`,
    and :meth:`circuit_state` with the correct signatures satisfies this
    protocol via structural subtyping.
    """

    async def should_allow(self, provider: str) -> bool:
        """Return whether requests to *provider* are currently allowed."""
        ...

    async def record_outcome(
        self, provider: str, *, success: bool, latency_ms: float
    ) -> None:
        """Record the outcome of a request to *provider*."""
        ...

    async def circuit_state(self, provider: str) -> CircuitState:
        """Return the current circuit state for *provider*."""
        ...
