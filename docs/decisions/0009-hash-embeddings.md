# Hash embeddings by default, with an API embedder behind the same function

## Decision

`EMBEDDING_BACKEND=hash` is the default. It hashes tokens into a 256-dimension vector, L2-normalises it, and stores that in `knowledge_chunks.embedding`. No weights are downloaded. `EMBEDDING_BACKEND=api` posts `{LLM_BASE_URL}/embeddings` and asks for the same 256 dimensions, so the column does not change. `EMBEDDING_BACKEND=fake` is the same algorithm with a different salt, used when a test must prove it is not the production embedder.

Retrieval score is cosine similarity plus a token-overlap bonus and a small heading match. Ranking runs in Python. The corpus is a few dozen sections.

## Alternatives

- A local sentence-transformer. Accurate on paraphrases, and it is a large download plus RAM. The same reason the chat model is hosted.
- Only the API embedder. Then `docker compose up` and CI spend money, or fail, before anyone has a key.
- A wider vector. 256 is enough for a hashed bag of words and matches `text-embedding-3-small` when that model is asked for 256 dimensions.

## Why

Policy questions in this corpus mostly repeat the section heading ("late fee", "duplicate charges"). A hashed bag of words plus an overlap bonus answers those without a model. The API embedder is there when someone wants a semantic one, and changing backend means reindexing because the two vectors are not comparable. The column width is fixed so that choice does not need a migration.
