# The ops queue approves credits on the existing endpoint

## Decision

The ops screen lists `pending_approval` adjustments and posts `decision=approve` or `decision=reject` to `/billAdjustment/{id}/approve`. The response records `decidedBy`. A second decision is a 409 from that endpoint, and the UI says the credit was already decided. The copilot still has no approve tool.

Unbars and plan changes are tabs on the same queue. They have no rows and no approve endpoint. The copilot is not allowed to unbar a line or change a plan. Those tabs say so, instead of inventing a write.

## Alternatives

- A new proposal table for unbars and plan changes, with its own approve route. That would be a second money-or-service write, and Phase 1 already has the credit path the deck's sample flow uses.
- Hiding the other two tabs. The deck lists unbar and plan change next to credits. An empty, labelled tab is more honest than a button that pretends to call an endpoint.

## Why

Slide 8 ends with a person approving a credit on the API that already exists. The UI should not grow a second way to change a bill. Service changes that the ledger cannot represent stay visible as future work, not as a silent apply.
