# CSR troubleshooting reuses the copilot

## Decision

`POST /agent/troubleshoot` is the CSR copilot with `flow=troubleshoot`. The CSR pastes an error or a symptom. The agent searches `docs/knowledge/csr-runbooks.md`, calls the read tools for that symptom, and calls `list_incidents` for the account. The answer is numbered steps plus a citation such as `[csr-runbooks.md § Failed payment]`. Related incidents are returned beside the answer. The trace name is `billpilot.troubleshoot`, with a `troubleshoot.start` span, using the same Langfuse hook as chat. CI still uses the fake model. The five new cases are in the eval harness. No hosted-model score is claimed.

The new runbook sections are Failed payment, Unbar not applied, Roaming not working, Bill not generated, and Entitlement missing. They do not contain currency amounts. An unbar question has to say "do not", because the input guardrail refuses a bare unbar instruction.

The assistant cannot post a payment, unbar a line, create an invoice, or grant units. Those sentences in the runbooks tell the CSR to hand the change to a person.

## Alternatives

- A second agent loop. The tools, guardrails, audit row, and fake model already exist.
- A static checklist with no account read. The deck asks the assistant to check the account and link incidents.
- A local model. The project stays on a hosted OpenAI-compatible API, with the fake model in CI.

## Why

Troubleshooting is another copilot turn with a narrower playbook and a few more runbook pages, not a new product surface.
