# resilience-ai

<!-- Badges placeholder -->
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Standalone resilience primitives for async Python. Circuit breakers, retry
with exponential backoff, token-bucket rate limiting, and rolling-window
health tracking -- all with **zero external dependencies** (stdlib only).

Extracted from [loom-ai](https://github.com/FlossWare/loom-ai) for
standalone use in any async Python project.

## Installation

```bash
pip install git+https://github.com/FlossWare/resilience-ai.git
```

## Quickstart

### Convenience decorators (recommended)

The fastest way to add resilience -- just decorate your async functions:

```python
from resilience_ai import with_retry, with_circuit_breaker, with_rate_limit

@with_retry(attempts=3, backoff=1.0)
async def call_api():
    """Retries up to 3 times with exponential backoff."""
    ...

@with_circuit_breaker(max_failures=5)
async def call_llm():
    """Opens circuit after 5 consecutive failures."""
    ...

@with_rate_limit(requests_per_second=10)
async def call_provider():
    """Throttles to 10 requests/second."""
    ...
```

All decorators are **explicit opt-in** -- importing `resilience_ai` does
nothing until you apply a decorator or construct a policy object.

### Retry with exponential backoff (full control)

```python
import asyncio
from resilience_ai import RetryPolicy, async_retry

policy = RetryPolicy(max_retries=3, backoff_base=2.0)

@async_retry(policy)
async def call_api():
    # Your unreliable API call here
    ...

asyncio.run(call_api())
```

### Circuit breaker (full control)

```python
import asyncio
from resilience_ai import CircuitBreakerPolicy

async def main():
    cb = CircuitBreakerPolicy(failure_threshold=5, recovery_timeout=60.0)

    # Check before calling
    if await cb.should_allow("openai"):
        try:
            result = await call_openai()
            await cb.record_outcome("openai", success=True, latency_ms=120.0)
        except Exception:
            await cb.record_outcome("openai", success=False, latency_ms=0.0)

    # Inspect state
    state = await cb.circuit_state("openai")
    print(f"State: {state.state}, failures: {state.failure_count}")

asyncio.run(main())
```

### Combined retry + circuit breaker

```python
from resilience_ai import CircuitBreakerPolicy, RetryPolicy, async_retry

cb = CircuitBreakerPolicy(failure_threshold=3)
policy = RetryPolicy(max_retries=2, backoff_base=1.5)

@async_retry(policy, resilience=cb, provider="anthropic")
async def call_anthropic(prompt: str) -> str:
    ...
```

### Composite resilience guard

```python
from resilience_ai import ResilientProvider

provider = ResilientProvider()

if await provider.should_allow("google"):
    result = await call_google()
    await provider.record_outcome("google", success=True, latency_ms=95.0)

# Get health snapshot
snapshot = provider.health_tracker.snapshot("google")
print(f"Error rate: {snapshot.error_rate:.1%}")
```

## API Overview

| Class / Function | Module | Description |
|------------------|--------|-------------|
| `with_retry` | `decorators` | Convenience decorator: retry with backoff |
| `with_circuit_breaker` | `decorators` | Convenience decorator: circuit breaker guard |
| `with_rate_limit` | `decorators` | Convenience decorator: token-bucket throttle |
| `CircuitBreakerPolicy` | `resilience` | Three-state circuit breaker (closed/open/half-open) |
| `RetryPolicy` | `retry` | Configurable retry with exponential backoff and jitter |
| `async_retry` | `retry` | Decorator factory combining retry + circuit breaker |
| `RateLimiter` | `rate_limiter` | Async token-bucket rate limiter with header parsing |
| `ProviderHealthTracker` | `provider_health` | Rolling-window latency and error-rate monitor |
| `SimpleRateLimiter` | `provider_health` | Synchronous token-bucket rate limiter |
| `ResilientProvider` | `provider_health` | Composite guard (circuit breaker + health + rate limiter) |
| `ResiliencePolicy` | `protocol` | `typing.Protocol` for custom implementations |
| `CircuitState` | `types` | Circuit breaker state snapshot dataclass |
| `BudgetStatus` | `types` | Token/cost budget status dataclass |

## Design Principles

- **Zero external dependencies** -- stdlib only (ADR-0008)
- **Explicit opt-in** -- nothing activates on import (ADR-0001)
- **Contracts over implementations** -- `typing.Protocol` for all extension points (ADR-0009)
- **Agent-neutral** -- no agent-specific code (ADR-0017)
- **Transport-independent** -- no REST/MCP/event coupling (ADR-0020)

See [STANDARDS.md](STANDARDS.md) for full FlossWare Engineering Standards compliance.

## License

MIT -- see [LICENSE](LICENSE) for details.
