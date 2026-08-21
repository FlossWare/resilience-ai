"""resilience-ai -- Standalone resilience primitives for async Python.

Circuit breakers, retry with exponential backoff, token-bucket rate
limiting, and rolling-window health tracking.  Zero external dependencies.
"""

from __future__ import annotations

from resilience_ai.protocol import ResiliencePolicy
from resilience_ai.provider_health import (
    HealthSnapshot,
    ProviderHealthTracker,
    ResilientProvider,
    SimpleRateLimiter,
)
from resilience_ai.rate_limiter import (
    ProviderLimits,
    RateLimitInfo,
    RateLimiter,
)
from resilience_ai.resilience import CircuitBreakerPolicy
from resilience_ai.retry import (
    CircuitOpenError,
    RetriesExhaustedError,
    RetryPolicy,
    async_retry,
)
from resilience_ai.decorators import (
    with_circuit_breaker,
    with_rate_limit,
    with_retry,
)
from resilience_ai.types import BudgetStatus, CircuitState

__all__ = [
    # Types
    "BudgetStatus",
    "CircuitState",
    "HealthSnapshot",
    "ProviderLimits",
    "RateLimitInfo",
    # Protocol
    "ResiliencePolicy",
    # Circuit breaker
    "CircuitBreakerPolicy",
    # Retry
    "CircuitOpenError",
    "RetriesExhaustedError",
    "RetryPolicy",
    "async_retry",
    # Rate limiting
    "RateLimiter",
    "SimpleRateLimiter",
    # Health tracking
    "ProviderHealthTracker",
    # Composite
    "ResilientProvider",
    # Convenience decorators (ADR-0006)
    "with_retry",
    "with_circuit_breaker",
    "with_rate_limit",
]

__version__ = "0.1"
