# Policy vectors live in the same Postgres

## Decision

Migration `002_agent` runs `CREATE EXTENSION vector` and adds `knowledge_chunks` with a `vector(256)` column. The API indexes the markdown under `docs/knowledge/` on startup when the text has changed.

There is no approximate-nearest-neighbour index. Search loads the chunks and ranks them in process.

## Alternatives

- A separate vector database. Another service to run for a few dozen rows.
- A `float8[]` column and no extension. Possible, and it throws away the type the column is for. pgvector is the usual Postgres answer and the image is `pgvector/pgvector:pg16`.
- An ANN index. The corpus does not have enough rows for the index to matter, and the score includes a token-overlap term that is easier to read in Python than in SQL.

## Why

Phase 1 already has one database. Putting chunks next to the ledger means one backup, one migration chain, and no new port. `knowledge_chunks` has no foreign key into the billing tables, so reseeding the ledger does not wipe the index.
