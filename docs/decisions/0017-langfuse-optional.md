# Langfuse tracing is off unless it is configured

Superseded for the product path by [0022](0022-langfuse-step-traces.md). The boolean flag described below has been removed. Tracing is on when the public key, secret key, and host are all set, and each turn records a span per step. The note is kept so the original "do not fail the request" choice stays readable.

## Decision

`LANGFUSE_ENABLED` defaults to false. When it is true, `trace_run` imports `langfuse` and sends one trace. The package is an optional extra (`pip install -e ".[tracing]"`). A missing package, a missing key, or a network error is logged and swallowed. The answer, the `agent_runs` row, and the audit row are already committed.

## Alternatives

- Always on. CI and a laptop demo would fail closed on a third-party host.
- OpenTelemetry only. Reasonable later. Langfuse is the product named for LLM traces, and it is one function behind a flag so it can be removed without touching the loop.

## Why

Tracing is for a person debugging a real run. It is not part of the correctness path. The system of record for a turn is `agent_runs`.

The deck drew a Langfuse trace on every step. That product work moved to Phase 3, with the UI and the free-tier deploy. This hook stays so Phase 3 can turn traces on without rewriting the loop, and so a missing host cannot take the copilot down.
