#!/bin/bash
# Add resilience-ai integration to your CLAUDE.md
set -e

CLAUDE_MD="${CLAUDE_MD:-./CLAUDE.md}"

if [ ! -f "$CLAUDE_MD" ]; then
    echo "Creating $CLAUDE_MD..."
    touch "$CLAUDE_MD"
fi

cat >> "$CLAUDE_MD" << 'BLOCK'

## Resilience (resilience-ai)

This project uses [resilience-ai](https://github.com/FlossWare/resilience-ai) for LLM call protection.

**Always wrap LLM API calls with resilience decorators:**

```python
from resilience_ai import with_retry, with_circuit_breaker, with_rate_limit

@with_rate_limit(requests_per_minute=60)
@with_circuit_breaker(provider="openai", max_failures=5)
@with_retry(max_attempts=3, backoff=1.0)
async def call_llm(prompt: str) -> str:
    ...
```

**Decorator stacking order:** rate_limit (outer) -> circuit_breaker -> retry (inner)

Install: `pip install "git+https://github.com/FlossWare/resilience-ai.git"`
BLOCK

echo "Added resilience-ai section to $CLAUDE_MD"
