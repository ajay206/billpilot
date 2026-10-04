# A migration batch is one transaction, and it can be rolled back

## Decision

A batch is loaded, dry-run, signed off, committed, or rolled back. Dry run writes reconciliation rows only. Commit inserts each accepted customer in the same database transaction, then checks that posted opening balances equal the accepted source total. If that check fails, or a row collides with the live ledger, the transaction rolls back. Running commit again on a committed batch writes nothing. Rollback deletes only the entities that batch linked, in child-first order, and leaves the seeded ledger alone. There is no `LOCK TABLE`. The other APIs keep serving. A file is capped at 500 records and one million characters.

## Alternatives

- A blue-green database cutover. That needs a second Postgres, which the free Render plan does not include.
- Upserting by MSISDN across batches. A second file that repeats a number would silently update a live subscriber. Idempotency is per batch id instead. A later batch that repeats a live MSISDN is rejected as a duplicate.

## Why

The deck requires a dry run with no writes, a reconciliation of counts and balances, re-runs that do not duplicate, and a rollback per batch id, while the APIs stay up. One transaction gives the all-or-nothing commit without taking the API down. The cap keeps a batch inside the 512 MB web instance. No new paid service is required.
