# PostgreSQL as the system of record

## Decision

Phase 1 stores the billing ledger in PostgreSQL. Money is `NUMERIC`, timestamps are `TIMESTAMPTZ`, and a few evidence payloads are `JSONB`. Tests run against PostgreSQL, not SQLite.

## Alternatives

- SQLite. Easier for a laptop demo, and wrong for the constraints we want to show: partial unique indexes (one open treatment per account), `JSONB`, and timestamp-with-timezone behaviour.
- A document store. Bills are relational. Accounts, lines, payments, and treatments join. A document model would hide the integrity rules inside the generator.

## Why

The architecture is a system of record with an API in front of it. Postgres is the usual choice for that shape, and the constraints (currency must be INR, a posted payment needs `posted_at`, subtotal + tax = total) are the thing a reviewer can point at. The ORM is a convenience for the API. The migration SQL is the contract.
