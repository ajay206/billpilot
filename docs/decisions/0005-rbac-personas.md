# Three personas, least privilege, API keys

The product UI no longer sends these keys. Sign-in, the session cookie, and the `users` table are [0024](0024-signed-session-cookie.md) and [0026](0026-demo-users.md). API keys remain for the CLI, curl, and the eval harness.

## Decision

Access is an `X-API-Key` header mapped to one of three roles.

- Customer: one customer number. Read own bills, usage, payments, products, and balances. Raise a dispute. Cannot open a general ticket, propose a credit, or approve one.
- CSR: one CSR code. The same reads, limited to accounts assigned to that code. Can open a ticket and propose an adjustment. Cannot approve. Opening a dispute or a ticket holds an active treatment; that hold is not a credit.
- Ops: read across accounts. The only role that can approve or reject. Cannot propose, and cannot open a dispute or a ticket. Ops is not a customer-chat identity.

The catalogue is readable by any authenticated role. `/health` and the docs are public.

## Alternatives

- One shared key. Fine for a toy, and it cannot demonstrate least privilege.
- Full OAuth and user records. Right for a product with real staff. Heavy for a mock whose point is the billing model. Keys are the seam; a later phase can swap the dependency that turns a header into a principal.

## Why

The three personas match the operating model: the customer sees their own account, the CSR works a queue, ops sees the estate and releases money. An id outside that scope returns 403 even when the row exists. A missing id returns 404. Hiding existence would also be reasonable; we chose the explicit 403 so a demo of "wrong CSR" is obvious, and we say so in the README.

Rate limits are per actor inside this process. They show the control. They are not a multi-instance limiter.
