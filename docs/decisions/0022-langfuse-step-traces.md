# Per-step Langfuse traces, on only when the three variables are set

## Decision

A copilot turn opens one Langfuse trace, `billpilot.chat`, when `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are all non-empty. The trace has a guardrail observation, a generation per model call (model, token counts, estimated cost), a tool observation per call, a retriever observation whose output lists the cited doc ids, an output-check observation, and a decision observation (`read`, `advise`, `propose`, or `refuse`). The trace id is a column on `agent_runs` and a field on `POST /agent/chat` and `GET /ops/agentRuns`.

The SDK is `langfuse` 4.x, imported only when the three variables are set. A missing package, a client that throws, or a flush that fails is logged and swallowed. The answer is already decided before flush. Evals clear the three variables so a harness run does not emit traces.

This replaces the single end-of-turn hook in [0017](0017-langfuse-optional.md). `LANGFUSE_ENABLED` is gone. Keys are the switch.

## Alternatives

- Keep the boolean flag. A flag without keys did nothing, and a flag plus keys is an extra step that a deploy would miss.
- OpenTelemetry only. Langfuse is the product the deck named, and the Hobby cloud tier is free.
- Fail the request when the exporter errors. Tracing is not the system of record. `agent_runs` is.

## Why

The deck asks for a trace of the prompt path, the tools, the documents, the decision, and the cost. One span at the end cannot show which tool ran or which doc was cited. Linking the id on the run row is how the ops screen points at that trace without Langfuse being required for the screen to render.
