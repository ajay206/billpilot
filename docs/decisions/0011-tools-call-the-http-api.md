# Tools call the HTTP API, not the database

## Decision

Every billing tool is an HTTP request to the Phase 1 routes, with the persona's `X-API-Key`. The model never sees SQL. `search_knowledge` is the exception: policy text is not a BSS resource, so that tool reads `knowledge_chunks`.

Inside the API process, the tool client cannot call `127.0.0.1` (one worker would deadlock on itself) and cannot run the ASGI app on the request thread (Starlette's portal deadlocks). `ThreadedASGITransport` runs the app on a worker thread and returns a buffered response the synchronous HTTP client can read. The CLI is a different process and uses `BSS_BASE_URL` instead.

## Alternatives

- Query the tables from the tool. Faster, and it skips the RBAC, the status translation, and the audit log the API already enforces. The copilot would be a second way into the ledger.
- A generic HTTP tool the model fills in. That is how a prompt-injection in a bill line becomes an arbitrary request. Tools are a fixed list with typed arguments.

## Why

The API is the product boundary. If a customer key cannot read another account, the copilot using that key cannot either. The thread hop is an implementation detail of in-process calls; the request that arrives is a normal HTTP request.
