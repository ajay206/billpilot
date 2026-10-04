# Alembic for revisions, hand-written SQL for the tables

## Decision

Schema changes are Alembic revisions. The first revision's upgrade and downgrade are SQL files, executed statement by statement. They are not generated from the ORM.

## Alternatives

- Alembic autogenerate from the SQLAlchemy models. Convenient, and the generated DDL is harder to review. Partial indexes and check constraints often come out wrong or missing.
- A pile of numbered `.sql` files and a shell loop. Works, but you then rebuild revision tracking, the `alembic_version` row, and a downgrade path that CI can run.

## Why

Reviewers should be able to read the constraints. The SQL file is that review. Alembic still records which revision is applied, which is what `migrate` on API startup needs. The ORM is checked against the live columns in tests, so the two cannot drift quietly. Seed truncates the billing tables and does not touch `alembic_version`.
