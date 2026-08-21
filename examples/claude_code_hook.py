#!/usr/bin/env python3
"""Claude Code hook: rate-limit and circuit-break outbound tool calls.

Install as a pre-tool hook in .claude/settings.json:
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash|WebFetch",
      "command": "python3 .claude/hooks/resilience_hook.py"
    }]
  }
}
"""
import asyncio
import json
import sys

from resilience_ai import CircuitBreakerPolicy, RateLimiter

limiter = RateLimiter(requests_per_minute=30)
cb = CircuitBreakerPolicy(max_failures=5, recovery_timeout=120.0)


async def check_resilience(tool_name: str) -> dict:
    if not await cb.should_allow(tool_name):
        return {
            "decision": "block",
            "reason": f"Circuit breaker open for {tool_name} — too many recent failures",
        }

    await limiter.acquire(tool_name)
    return {"decision": "approve"}


def main() -> None:
    event = json.load(sys.stdin)
    tool_name = event.get("tool_name", "unknown")
    result = asyncio.run(check_resilience(tool_name))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
