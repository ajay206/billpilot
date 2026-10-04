# One call opens a line, and the first bill stays a preview

## Decision

`POST /onboarding` and `POST /tmf-api/customerManagement/v4/onboarding` are the same handler. CSR and ops can call it. The customer role cannot. The call validates the MSISDN, phone, email, cycle day, plan, and VAS, then writes the customer, account, subscription, plan entitlements, opted-in VAS, a treatment at stage `none`, and a credit profile of class `new` with a limit of twice the monthly fee. The response includes a welcome message and a first-bill preview. That preview is not an invoice.

## Alternatives

- Three TMF creates (party, billing account, product) that the client stitches together. A failure between them leaves a customer with no line.
- Posting the first bill immediately. Collections would start before the customer has seen a bill run.

## Why

The deck's new sale is one API call that leaves the line ready and the first bill readable. Posting that preview would put money on the ledger that the customer does not owe yet. A migrated opening balance is the opposite case: that money is already owed, so it becomes an invoice with tax zero and the source amount copied through.
