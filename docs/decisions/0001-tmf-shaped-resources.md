# TMF-shaped resources, not a certified API

## Decision

The mock BSS exposes resources named like TM Forum Open APIs: TMF678 Customer Bill, TMF635 Usage, TMF620 Product Catalog, TMF676 Payment, TMF637 Product Inventory, TMF621 Trouble Ticket, and a TMF654-style balance. The database keeps a smaller internal vocabulary. The API translates.

## Alternatives

- Invent a private REST shape. Faster to write, and useless as a teaching API. A later agent would learn names that do not exist outside this repo.
- Implement the full Open API schemas and aim at certification. That is a large spec surface (polymorphic relationships, every optional field, conformance kits) and it is not what Phase 1 is for.

## Why

Interviewers will ask whether this is "real TMF". The honest answer is: the resource names, the main fields, and the separation of bill / usage / payment / inventory match the Open APIs, and the README says it is a learning mock. Signed line amounts are kept so the lines add up to the bill total. A strict TMF reading often uses magnitudes plus a type. We chose the sum to be checkable by hand.

Internal statuses stay stable (`issued`, `posted`, `soft_bar`) so the ledger does not have to change when the facade wording does.
