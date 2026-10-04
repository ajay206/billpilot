# Demo users on the ledger, no admin role

## Decision

Migration `004_users` adds `users`. A row has a username, a display name, an Argon2id password hash, a role (`customer`, `csr`, or `ops`), and one scope: a customer number or a CSR code. Ops has neither. There is no admin role.

Six synthetic users are inserted when the ledger is seeded, and again on boot when the ledger already has customers and a username is missing. Seeding truncates billing tables only. It does not drop `users`. An existing Neon database gets the table from `alembic upgrade` and the six rows from `seed-if-empty`, without a wipe.

The published demo passwords are `demo-priya`, `demo-arjun`, `demo-neha`, `demo-ananya`, `demo-vikram`, and `demo-meera`. They are for this portfolio only. `GET /auth/demo-accounts` returns them so the login page and the seed cannot drift. They are not credentials for any real system.

Customer users: Priya Sharma (`CUST-000001`), Arjun Mehta (`CUST-000003`), Neha Iyer (`CUST-000005`). CSR users: Ananya Rao (`CSR-A`), Vikram Nair (`CSR-B`). Ops: Meera Kapoor. Even customer indexes are `CSR-A`, which is the generator's existing rule, so Priya's account is on Ananya's book.

Those three customer rows use the sign-in names. The generator still draws a Faker name for the index, then replaces it, so the rest of the ledger stays on the same sequence. `seed-if-empty` runs the same rename on a database that was seeded before this change. It updates only those three holders, and a second boot finds the names already match.

## Alternatives

- An admin role that can create users. Nothing in the product asks for user administration. Ops already reads every account and is the only approver. A fourth role would be a key with no screen.
- A foreign key from `users.customer_number` to `customers`. A re-seed replaces customer ids. The business key `CUST-000001` is stable for seed 42, so the scope column is that string, same as the API-key principal.
- Putting the demo passwords in the migration. The hash would be frozen in SQL. The Python seeder uses the same Argon2 helper as a password change would, and it can run against a database that already has customers.

## Why

The UI can no longer choose a persona. The row is the principal. Boot has to add those rows to a database that was seeded before this migration, and it must not reload 48 or 500 customers to do it. `users` stays out of the generator's truncate list for that reason.
