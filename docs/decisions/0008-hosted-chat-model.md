# A cheap hosted chat model, called through an OpenAI-compatible API

## Decision

The copilot calls one chat model over HTTP. `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` name the host, the model, and the key. The default model name is `gpt-4o-mini`. The client posts `{base}/chat/completions` and reads tool calls from the response. Token counts come from the usage object when the host sends one, otherwise from a character estimate. Cost is `tokens × price` from a small table in `billpilot.agent.cost`, overridable with `LLM_PRICE_TABLE`.

There is no local model runtime in this repository.

## Alternatives

- Ollama, or any other local model. The architecture deck named this. It was rejected: a laptop that is already running Postgres and the API cannot spare the RAM, and CI would need a model image.
- A framework that hides the HTTP call (LangChain, LlamaIndex, and similar). The loop is a few dozen lines: send tools, append the tool result, stop at a budget. A framework would make that loop harder to explain in an interview.

## Why

A hosted model keeps the laptop light and keeps the provider replaceable. Any host that speaks the chat-completions shape works, including a cheap one. The price table makes the spend visible per call and per eval run. The fake backend in `0016` is what tests and CI use, so the hosted call is opt-in.
