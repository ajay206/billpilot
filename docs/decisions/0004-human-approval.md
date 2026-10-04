# A person approves money and service changes

## Decision

The only money write in Phase 1 is "propose an adjustment". It is inserted as `pending_approval` and does not change the invoice. An ops caller applies or rejects it on `/billAdjustment/{id}/approve`. The proposer cannot approve their own row. Apply and the invoice update commit together. Reject leaves the bill as it was.

Opening a dispute can hold an active treatment. That is a protective hold, not a credit.

## Alternatives

- Let the API, or a later agent, post the credit immediately. Simple, and it is the failure mode the product is supposed to avoid: a model that moves money with no second person.
- A separate "approved but not applied" status. Two steps to forget. Apply is the approval.

## Why

The governance rule is that a copilot proposes and a person disposes, and the person who proposes is not the person who disposes. The status column and the 403 on self-approval are that rule in code. The audit log records propose, apply, and reject with the actor.
