# resilience-ai Integration Guide

Install:
```bash
pip install "git+https://github.com/FlossWare/resilience-ai.git"
```

---

## Claude Code

### CLAUDE.md snippet

Add to your project's `CLAUDE.md`:

```markdown
## Resilience

This project uses `resilience-ai` for LLM call protection.
Always wrap LLM calls with retry, circuit-breaker, or rate-limit decorators.

```python
from resilience_ai import with_retry, with_circuit_breaker, with_rate_limit

@with_retry(max_attempts=3, backoff=1.0)
@with_circuit_breaker(provider="openai", max_failures=5)
async def call_llm(prompt: str) -> str:
    ...
```
```

### Hooks

**Pre-tool hook** (`hooks/pre-tool-resilience.py`):
```python
#!/usr/bin/env python3
"""Claude Code hook: rate-limit outbound LLM calls."""
import json, sys
from resilience_ai import RateLimiter

limiter = RateLimiter(requests_per_minute=60, tokens_per_minute=100_000)

event = json.load(sys.stdin)
if event.get("tool_name") in ("Bash", "WebFetch"):
    import asyncio
    asyncio.run(limiter.acquire("default"))

print(json.dumps({"decision": "approve"}))
```

**Post-tool hook** (`hooks/post-tool-resilience.py`):
```python
#!/usr/bin/env python3
"""Claude Code hook: track tool call failures for circuit-breaker."""
import json, sys
from resilience_ai import CircuitBreakerPolicy

cb = CircuitBreakerPolicy(max_failures=5, recovery_timeout=60.0)

event = json.load(sys.stdin)
tool = event.get("tool_name", "unknown")
if event.get("error"):
    import asyncio
    asyncio.run(cb.record_failure(tool))
else:
    import asyncio
    asyncio.run(cb.record_success(tool))

print(json.dumps({"decision": "approve"}))
```

### Skills

Create `.claude/skills/resilient-call.md`:
```markdown
---
name: resilient-call
description: Make a resilient LLM call with retry and circuit-breaker
---

Use resilience-ai decorators to wrap the call:
- @with_retry for transient failures
- @with_circuit_breaker for persistent failures
- @with_rate_limit for rate limiting
```

---

## OpenAI Codex

### AGENTS.md snippet
```markdown
## Tools

This agent uses `resilience-ai` for fault tolerance.
All LLM backend calls must use retry and circuit-breaker patterns:

```python
from resilience_ai import with_retry, with_circuit_breaker

@with_retry(max_attempts=3, backoff=2.0)
@with_circuit_breaker(provider="openai", max_failures=5)
async def tool_call(prompt: str) -> str:
    ...
```
```

### Tool definition
```python
from resilience_ai import RetryPolicy, CircuitBreakerPolicy

retry = RetryPolicy(max_attempts=3, backoff_base=1.0)
cb = CircuitBreakerPolicy(max_failures=5, recovery_timeout=60.0)

async def resilient_tool(prompt: str) -> str:
    return await retry.execute(
        lambda: cb.execute("openai", lambda: call_llm(prompt))
    )
```

---

## Cursor

### .cursorrules snippet
```
When making LLM API calls, always use resilience-ai decorators:
- @with_retry(max_attempts=3) for transient failures
- @with_circuit_breaker(provider="name", max_failures=5) for cascading failures
- @with_rate_limit(requests_per_minute=60) for rate limiting

Import from: from resilience_ai import with_retry, with_circuit_breaker, with_rate_limit
Package: pip install "git+https://github.com/FlossWare/resilience-ai.git"
```

### Cursor Composer integration
Add to Composer instructions:
```
Use resilience-ai for all external API calls. Stack decorators:
@with_rate_limit → @with_circuit_breaker → @with_retry → async def fn()
```

---

## Crush

### Configuration
```python
from crush import Agent
from resilience_ai import with_retry, with_circuit_breaker

class ResilientAgent(Agent):
    @with_retry(max_attempts=3, backoff=1.0)
    @with_circuit_breaker(provider="default", max_failures=5)
    async def call_model(self, prompt: str) -> str:
        return await self.backend.chat(prompt)
```

---

## Generic Python Agent

### asyncio integration
```python
import asyncio
from resilience_ai import (
    with_retry, with_circuit_breaker, with_rate_limit,
    RetryPolicy, CircuitBreakerPolicy, RateLimiter,
)

# Decorator approach (simplest)
@with_retry(max_attempts=3, backoff=1.0)
@with_circuit_breaker(provider="openai", max_failures=5)
@with_rate_limit(requests_per_minute=60)
async def call_llm(prompt: str) -> str:
    # Your LLM call here
    ...

# Programmatic approach (more control)
retry = RetryPolicy(max_attempts=3, backoff_base=1.0)
cb = CircuitBreakerPolicy(max_failures=5, recovery_timeout=60.0)
limiter = RateLimiter(requests_per_minute=60)

async def call_with_resilience(prompt: str) -> str:
    await limiter.acquire("openai")
    if not await cb.should_allow("openai"):
        raise Exception("Circuit open")
    try:
        result = await your_llm_call(prompt)
        await cb.record_success("openai")
        return result
    except Exception as e:
        await cb.record_failure("openai")
        raise
```

---

## Cross-Package Integration

### Recommended decorator stacking order
```
@with_rate_limit        # outermost: enforce rate limits first
@with_circuit_breaker   # then: check circuit state
@with_retry             # innermost: retry on transient failure
@track_execution        # (observability-ai) log metrics
@mask_secrets           # (security-ai) redact secrets from output
async def call_llm(prompt: str) -> str:
    ...
```

### With observability-ai
```python
from resilience_ai import with_retry, with_circuit_breaker
from observability_ai import track_execution, ExecutionTelemetry

telemetry = ExecutionTelemetry()

@with_retry(max_attempts=3, backoff=1.0)
@with_circuit_breaker(provider="openai", max_failures=5)
@track_execution(telemetry=telemetry, provider="openai")
async def call_llm(prompt: str) -> str:
    ...
```

### With security-ai
```python
from resilience_ai import with_retry
from security_ai import mask_secrets

@with_retry(max_attempts=3)
@mask_secrets(patterns=[r'(sk-)[a-zA-Z0-9]+'])
async def call_llm(prompt: str) -> str:
    ...
```

### With model-router-ai
```python
from resilience_ai import with_retry, with_circuit_breaker
from model_router_ai import CostAware, BudgetGuard

# resilience-ai protects the router
@with_retry(max_attempts=3)
@with_circuit_breaker(provider="router", max_failures=5)
async def route_and_call(prompt: str) -> str:
    router = CostAware(BudgetGuard(your_backend))
    return await router.chat(prompt)
```
