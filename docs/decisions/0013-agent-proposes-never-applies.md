# The copilot proposes a credit and cannot apply it

## Decision

`propose_adjustment` is a POST to `/billAdjustment`. The API stores `pending_approval` and does not change the invoice. There is no tool that calls `/billAdjustment/{id}/approve`. If a tool result, or the model's draft, says a credit was applied, the answer is replaced and the run is marked as needing a person.

Ops still approves through the existing endpoint, with a different API key. That path is unchanged from Phase 1.

## Alternatives

- An approve tool gated to ops. Convenient, and it puts money movement one model decision away from a prompt injection. The governance rule is a second person, not a second prompt.
- Let the model compute a new invoice total. The API already applies the line on approval, and it does not recompute GST. The copilot should not invent a second formula.

## Why

Slide 8 of the architecture is dispute, then propose, then a person approves. The missing tool is the enforcement. The status column and the self-approval 403 from Phase 1 stay the enforcement on the API side. A scripted model in tests proposes a credit and the bill total is asserted unchanged.
