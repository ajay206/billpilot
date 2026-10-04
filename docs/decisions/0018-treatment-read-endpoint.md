# Treatment is readable as a billing-account resource

## Decision

Phase 2 adds `GET /tmf-api/accountManagement/v4/billingAccount` and `GET /tmf-api/accountManagement/v4/billingAccount/{id}`. The body includes the treatment stage, status, hold reason, and any current exemption. The copilot's `get_treatment` tool calls that route. Nothing here writes a bar or a hold.

## Alternatives

- Hide treatment inside the bill payload. A bill and a collections state are different resources, and a hold can exist with no new bill.
- A purpose-built `/treatment` path. The account resource is the TMF-shaped place for this, and the tool stays an HTTP call like the others.

## Why

The ledger already stored treatment in Phase 1 and the API never returned it, so the copilot could not check a bar or a hold. This is a read added so the tool can stay on the API. It is not a certified TMF666 implementation. The payload is the subset the use case needs.
