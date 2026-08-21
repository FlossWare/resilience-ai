# resilience-ai Integration Guide

`resilience-ai` is a standalone, agent-neutral Python capability. It does not require Loom or any agent runtime. Install it directly in the project being developed by Claude Code, Cursor, Crush, OpenCode, or another agent:

```bash
pip install "git+https://github.com/FlossWare/resilience-ai.git"
```

---

## Direct Python usage

```python
from resilience_ai import with_retry, with_circuit_breaker, with_rate_limit

@with_rate_limit(requests_per_second=10)
@with_circuit_breaker(provider="openai", max_failures=5)
@with_retry(attempts=3, backoff=1.0)
async def call_llm(prompt: str) -> str:
    ...
```

The decorators are explicit, composable, and independent of Loom.

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

@with_rate_limit(requests_per_second=10)
@with_circuit_breaker(provider="openai", max_failures=5)
@with_retry(attempts=3, backoff=1.0)
async def call_llm(prompt: str) -> str:
    ...
```
```

### Skill

Create `.claude/skills/resilient-call.md`:

```markdown
---
name: resilient-call
description: Make resilient LLM calls with retry, circuit breaker, and rate limiting
---

Use `resilience-ai` directly. Do not introduce a Loom dependency merely to use resilience.
```

---

## OpenAI Codex

Add the equivalent guidance to `AGENTS.md`:

```markdown
## Resilience

Use `resilience-ai` directly for external LLM calls. Prefer:
`@with_rate_limit` -> `@with_circuit_breaker` -> `@with_retry`.
Install with `pip install "git+https://github.com/FlossWare/resilience-ai.git"`.
```

---

## Cursor

Add to project instructions / `.cursorrules`:

```text
Use resilience-ai for LLM/API fault tolerance. Do not add a Loom dependency.
Prefer @with_rate_limit, @with_circuit_breaker, and @with_retry from resilience_ai.
Install: pip install "git+https://github.com/FlossWare/resilience-ai.git"
```

---

## Crush

Add the same project-level instruction or use the Python API directly:

```python
from resilience_ai import with_retry, with_circuit_breaker

@with_retry(attempts=3, backoff=1.0)
@with_circuit_breaker(provider="default", max_failures=5)
async def call_model(prompt: str) -> str:
    ...
```

No Crush runtime import is required by `resilience-ai` itself.

---

## OpenCode

Add the same instruction to the OpenCode project configuration/context:

```text
Use resilience-ai directly for LLM/API resilience.
Install: pip install "git+https://github.com/FlossWare/resilience-ai.git"
Use @with_retry(attempts=3), @with_circuit_breaker(...), and @with_rate_limit(...).
Do not require Loom for resilience functionality.
```

---

## Generic Python Agent

```python
import asyncio
from resilience_ai import (
    with_retry, with_circuit_breaker, with_rate_limit,
    RetryPolicy, CircuitBreakerPolicy, RateLimiter,
)

@with_retry(attempts=3, backoff=1.0)
@with_circuit_breaker(provider="openai", max_failures=5)
@with_rate_limit(requests_per_second=1)
async def call_llm(prompt: str) -> str:
    ...
```

Use the policy classes when explicit lifecycle/state control is required.

---

## Cross-Package Integration

### Recommended decorator stacking order

```text
rate limit -> circuit breaker -> retry -> execution telemetry -> output security
```

For example:

```python
from resilience_ai import with_retry, with_circuit_breaker, with_rate_limit
from observability_ai import track_execution, ExecutionTelemetry
from security_ai import mask_secrets

telemetry = ExecutionTelemetry()

@with_rate_limit(requests_per_second=10)
@with_circuit_breaker(provider="openai", max_failures=5)
@with_retry(attempts=3, backoff=1.0)
@track_execution(telemetry=telemetry, name="call-llm", provider="openai")
@mask_secrets(patterns=[r"(sk-)[a-zA-Z0-9]+"])
async def call_llm(prompt: str) -> str:
    ...
```

The same components can be composed in Loom, but Loom is optional.
