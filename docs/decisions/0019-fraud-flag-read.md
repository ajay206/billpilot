# Fraud flags are a read, because the usage rows are not the whole pattern

## Decision

`GET /accountManagement/v4/fraudFlag` returns the synthetic `fraud_flags` rows for accounts in the caller's scope. The copilot tool is `list_fraud_flags`. It is a read. Nothing here opens, closes, or credits a flag.

The usage tool also keeps unbilled, duplicate, roaming, and premium-rate rows in its projection, so those patterns are visible even when a flag was not written.

## Alternatives

- Leave the table unread. The SIM-swap case is "the SIM changed, then a short burst of premium-rate calls". The product resource only has the new SIM. Without the flag, the copilot cannot tell a swap from an ordinary handset.
- A write API that clears flags. That is a service change. It belongs on the approval queue, which this phase does not extend.

## Why

Revenue-assurance questions are in the Phase 2 case mix. The ledger already stored the flags in Phase 1 and no route returned them, so the tool-calling rule ("HTTP, not SQL") had nothing to call. The path is not a TM Forum API. The README says so.
