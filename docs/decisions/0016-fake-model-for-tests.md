# Tests and CI use a scripted model

## Decision

`LLM_BACKEND=fake` is the default. `FakeChatModel` reads the user message, picks one tool from a fixed playbook (explain a bill, investigate a duplicate, answer from policy, read treatment, read a balance, read payments), and writes the answer from the JSON the tool returned. It does not open a socket. Its token counts are `len(text) // 4` and its price is zero.

`ScriptedChatModel` is a thinner stub for tests that need a specific tool sequence, including a hallucinated approve call.

CI runs `pytest`, which includes the eval harness on this backend. That smoke test checks refusals, the absence of an approve tool, and that a report was written. It does not claim a quality score.

## Alternatives

- A recorded cassette of a real model. Brittle, and it smuggles a provider response into the repo.
- Skip agent tests in CI. Then the tool allowlists and the propose-not-apply rule rot.

## Why

The harness has to run on every pull request with no key, no network, and no spend. A scripted model makes the tool path deterministic: given a duplicate line, it proposes that line's pre-tax amount and stops. Accuracy against ground truth is a metric for a real model run, which is why the README table is empty until someone runs `--backend api`.
