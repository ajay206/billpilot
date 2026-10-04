# Each persona sees a different tool list

## Decision

`tools_for(persona)` filters a static list. Customers and CSRs and ops can read bills, usage, payments, products, balances, offerings, treatment, disputes, and adjustments, and can search policy. A customer or a CSR can open a dispute. Only a CSR can open a ticket or propose a credit. Only ops can read the audit log. The executor rejects a name that is not on that persona's list, including any name containing `approve`.

A customer session also pins the account returned for that API key. A tool argument that names a different account is rejected before the call.

## Alternatives

- One tool list, and trust the API to 403 the rest. The API does 403, and the model would still be offered actions it must not take. Least privilege is the list the model is shown, not only the check behind it.
- Per-user policies in a database. Three personas are the whole product. A table would hide a list that fits on one screen.

## Why

The interview question is "what can the customer copilot do that the ops copilot cannot, and the reverse?" The answer is the `roles` set on each tool, plus the API key the tool sends. Ops is not given `propose_adjustment` because the proposer cannot approve their own row, and the copilot must not be the proposer and the approver.
