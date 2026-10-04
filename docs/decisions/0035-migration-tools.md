# The copilot can read a migration batch and cannot run one

## Decision

Ops tools `list_migration_batches`, `get_migration_batch`, and `list_migration_rejects` call the migration GET routes with the ops key. Customer and CSR do not receive those tools. Asking to commit, sign off, or roll back a batch is refused before the model runs. A customer who asks about a migration batch is out of scope. CI covers this with the fake model.

## Alternatives

- A commit tool gated by a prompt. The existing rule is that the model never applies a money or service change, and a prompt is not a gate.
- Letting CSR run the batch. The deck puts the migration desk with ops. CSR can onboard one customer and cannot load a file.

## Why

Ops needs to ask what a batch did and why rows were rejected. The same guardrail that blocks an approve tool blocks a migration write. The eval cases check the read tools and both refusals, and the fake model keeps that check off a real key.
