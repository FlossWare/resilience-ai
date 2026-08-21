#!/usr/bin/env python3
"""Verify resilience-ai installation."""
import asyncio
import sys


def main() -> int:
    try:
        from resilience_ai import (
            CircuitBreakerPolicy,
            RateLimiter,
            RetryPolicy,
            with_circuit_breaker,
            with_rate_limit,
            with_retry,
        )
    except ImportError as e:
        print(f"FAIL: Cannot import resilience-ai: {e}")
        print("Install: pip install 'git+https://github.com/FlossWare/resilience-ai.git'")
        return 1

    from resilience_ai import __version__

    print(f"resilience-ai v{__version__} installed successfully.")
    print(f"  CircuitBreakerPolicy: {CircuitBreakerPolicy}")
    print(f"  RetryPolicy:          {RetryPolicy}")
    print(f"  RateLimiter:          {RateLimiter}")
    print(f"  Decorators:           @with_retry, @with_circuit_breaker, @with_rate_limit")

    # Smoke test
    cb = CircuitBreakerPolicy(max_failures=3, recovery_timeout=10.0)
    assert asyncio.run(cb.should_allow("test")) is True
    print("  Smoke test:           PASS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
