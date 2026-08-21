# FlossWare Engineering Standards Compliance

This repository implements the following ADRs from
[FlossWare/engineering-standards](https://github.com/FlossWare/engineering-standards):

| ADR | Title | How resilience-ai complies |
|-----|-------|---------------------------|
| [ADR-0001](https://github.com/FlossWare/engineering-standards/blob/main/adr/ADR-0001.md) | Explicit Opt-In | No behavior activates on import. Circuit breakers, retry, and rate limiters must be explicitly constructed or applied via decorators. |
| [ADR-0006](https://github.com/FlossWare/engineering-standards/blob/main/adr/ADR-0006.md) | Cross-Cutting Decorators | Convenience decorators (`@with_retry`, `@with_circuit_breaker`, `@with_rate_limit`) wrap async functions for common resilience patterns. |
| [ADR-0008](https://github.com/FlossWare/engineering-standards/blob/main/adr/ADR-0008.md) | Free-First | Zero external dependencies. Uses only the Python standard library. |
| [ADR-0009](https://github.com/FlossWare/engineering-standards/blob/main/adr/ADR-0009.md) | Core Principles | Modular and composable. All extension points use `typing.Protocol` (contracts over implementations). |
| [ADR-0017](https://github.com/FlossWare/engineering-standards/blob/main/adr/ADR-0017.md) | Agent-Neutral | No agent-specific code. Works with any agent runtime (Claude Code, Codex, Crush, etc.). |
| [ADR-0020](https://github.com/FlossWare/engineering-standards/blob/main/adr/ADR-0020.md) | Capability-Protocol Separation | Resilience capabilities are independent of transport protocol. No REST, MCP, or event coupling. |
