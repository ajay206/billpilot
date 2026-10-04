# Every copilot turn is an agent_runs row linked to audit_log

## Decision

Migration `002_agent` adds `agent_runs`. One row stores the persona, the account, the user message, the system prompt, the tool calls, the citations, the proposed actions, the answer, the refusal reason, the model name, the prompt and completion token counts, the estimated cost, and the latency. `audit_log_id` points at the summary row written in the same transaction (`action = agent.chat`). Both rows share `request_id`.

The full prompt is on `agent_runs`. The audit payload is a short summary, which is what the ops audit screen is for.

## Alternatives

- Only the audit log. The payload would either drop the prompt or bloat every audit row with it. The two tables have two readers: ops scanning actions, and someone reconstructing a copilot turn.
- A log file. Files do not join to `audit_log`, and they disappear with the container.

## Why

Slide 13 asks for a record of what the copilot saw, what it called, what it proposed, and what it cost. The foreign key is the link between "the model proposed a credit" and "the ledger recorded that proposal". Reseeding truncates `audit_log` and therefore `agent_runs`. The policy index is not part of that cascade.
