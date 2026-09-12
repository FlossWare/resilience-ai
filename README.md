# resilience

Reusable resilience primitives for FlossWare: retry, circuit breaking, rate limiting, and health tracking.

## Architectural boundary

Resilience changes **how an already-authorized operation is attempted**, not whether that operation is semantically required or permitted.

```text
Loom Worker / model-gateway / capability
                |
                v
          resilience policy
          retry / breaker / rate limit
                |
                v
             operation
```

- authorization, safety, policy, and budget remain hard constraints outside learned optimization.
- `model-gateway` may use resilience for provider calls.
- Loom may use resilience around Worker/tool execution.
- resilience must not become orchestration, routing, or Knowledge.

Keep policies composable, explicit, transport-independent, and replaceable.

## Status

Active supporting capability. It was extracted from Loom and should remain reusable across Loom and non-Loom applications.

## License

MIT
