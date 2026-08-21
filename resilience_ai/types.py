"""Shared data types for the resilience-ai package.

Uses only the standard library -- zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CircuitState:
    """Snapshot of a circuit breaker's state for a single provider."""

    state: str
    failure_count: int
    last_failure_at: str = ""
    next_retry_at: str = ""


@dataclass
class BudgetStatus:
    """Token/cost budget status for a provider or session."""

    tokens_used: int
    tokens_remaining: int | None
    cost_used: float
    cost_remaining: float | None
