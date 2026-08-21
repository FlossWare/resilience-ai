#!/usr/bin/env python3
"""Basic resilience-ai usage example.

Demonstrates retry, circuit-breaker, and rate-limiting decorators
wrapping a simulated LLM call.
"""
import asyncio
import random

from resilience_ai import with_circuit_breaker, with_rate_limit, with_retry


# Simulated flaky LLM call
async def _raw_llm_call(prompt: str) -> str:
    if random.random() < 0.3:
        raise ConnectionError("API timeout")
    return f"Response to: {prompt}"


# Protected with all three resilience layers
@with_rate_limit(requests_per_minute=60)
@with_circuit_breaker(provider="demo", max_failures=5)
@with_retry(max_attempts=3, backoff=0.1)
async def resilient_llm_call(prompt: str) -> str:
    return await _raw_llm_call(prompt)


async def main() -> None:
    for i in range(5):
        try:
            result = await resilient_llm_call(f"Question {i + 1}")
            print(f"  [{i + 1}] OK: {result}")
        except Exception as e:
            print(f"  [{i + 1}] FAIL: {e}")


if __name__ == "__main__":
    print("resilience-ai basic usage example")
    print("=" * 40)
    asyncio.run(main())
