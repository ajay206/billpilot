"""Text embeddings.

The default is a hashed token embedder: no weights, no download, no API spend.
An OpenAI-compatible /embeddings call is the other backend, behind the same
function. Tests use a deterministic fake that does not touch the network.
"""

import hashlib
import math
import re
from typing import Protocol

import httpx

from billpilot.config import Settings

# Shared with the pgvector column. The API embedder asks for this width.
EMBEDDING_DIM = 256

_TOKEN = re.compile(r"[a-z0-9]+")
# Function words are left out of the overlap bonus. They are in almost every
# question, so counting them makes every section look equally relevant.
_STOP = frozenset(
    "a an the is are was were be been being of to and or on in for with from by at as "
    "what when who how does do did should can could would will just than then that this "
    "it its not into about your my our their".split()
)


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def content_tokens(text: str) -> set[str]:
    return {token for token in tokenize(text) if token not in _STOP and len(token) > 2}


def _l2(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]


def _hash_vector(text: str, *, salt: bytes) -> list[float]:
    """Bag of hashed tokens, L2-normalised. The same text always returns the same vector."""
    vector = [0.0] * EMBEDDING_DIM
    tokens = tokenize(text)
    grams = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:], strict=False)]
    for token in grams:
        digest = hashlib.sha256(salt + token.encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return _l2(vector)


class HashEmbedder:
    """Default embedder. Lexical, tiny, and free on a laptop."""

    name = "hash"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_vector(text, salt=b"billpilot-hash-v1") for text in texts]


class FakeEmbedder:
    """Deterministic stand-in for tests. It never calls a network or loads weights."""

    name = "fake"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_vector(text, salt=b"billpilot-fake-v1") for text in texts]


class ApiEmbedder:
    """POST {base}/embeddings. The body asks for EMBEDDING_DIM so the column still fits."""

    name = "api"

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise RuntimeError("EMBEDDING_BACKEND=api requires LLM_API_KEY.")
        self._settings = settings

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = self._settings.llm_base_url.rstrip("/") + "/embeddings"
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
            json={
                "model": self._settings.embedding_model,
                "input": texts,
                "dimensions": EMBEDDING_DIM,
            },
            timeout=self._settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda row: row["index"])
        vectors = [list(row["embedding"]) for row in rows]
        for vector in vectors:
            if len(vector) != EMBEDDING_DIM:
                raise RuntimeError(
                    f"Embedding endpoint returned {len(vector)} dimensions; the column is {EMBEDDING_DIM}."
                )
        return vectors


def build_embedder(settings: Settings) -> Embedder:
    backend = settings.embedding_backend
    if backend == "hash":
        return HashEmbedder()
    if backend == "fake":
        return FakeEmbedder()
    if backend == "api":
        return ApiEmbedder(settings)
    raise RuntimeError(f"Unknown EMBEDDING_BACKEND {backend!r}. Use hash, api, or fake.")


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def rank_score(query: str, query_vector: list[float], section: str, body: str, body_vector: list[float]) -> float:
    """Cosine, token overlap, and a heading match.

    The hash embedder is lexical. Overlap keeps a question that says "GST" on
    the GST section when several sections share the word "bill". The heading
    term prefers the section whose title the question actually repeats, so
    "Failed autopay that later posted" beats the shorter "Failed autopay".
    A semantic embedder still works with the same score: the extra terms are
    a signal, not a replacement.
    """
    query_tokens = content_tokens(query)
    if not query_tokens:
        return cosine(query_vector, body_vector)
    section_tokens = content_tokens(section)
    doc_tokens = section_tokens | content_tokens(body)
    overlap = len(query_tokens & doc_tokens) / len(query_tokens)
    # A small weight. It breaks a near-tie when the question repeats the
    # heading ("duplicate charges") and stays too small to let a short
    # partial title ("a deposit is not credit") beat a closer section.
    heading = 0.0
    if section_tokens:
        shared = query_tokens & section_tokens
        heading = 0.2 * (len(shared) / len(section_tokens) + len(shared) / len(query_tokens))
    return cosine(query_vector, body_vector) + overlap + heading
