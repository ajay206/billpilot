"""Load the synthetic policy corpus and retrieve sections.

Vectors are stored in Postgres with pgvector. Ranking runs in this process:
the corpus is a few dozen sections, and the score (cosine plus token overlap)
is easier to explain here than in a SQL expression.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from billpilot.agent.embeddings import Embedder, rank_score
from billpilot.agent.guardrails import format_citation
from billpilot.models import KnowledgeChunk


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    title: str
    section: str
    source_path: str
    body: str


def knowledge_root() -> Path:
    """The markdown corpus.

    A source checkout keeps `docs/knowledge` three levels above this file.
    An installed package (the Docker image) does not, so the process working
    directory is the next place to look. `WORKDIR` in the image is `/app`.
    """
    checkout = Path(__file__).resolve().parents[3] / "docs" / "knowledge"
    if checkout.is_dir():
        return checkout
    working = Path.cwd() / "docs" / "knowledge"
    if working.is_dir():
        return working
    return checkout


def load_chunks(root: Path | None = None) -> list[Chunk]:
    root = root or knowledge_root()
    if not root.is_dir():
        raise FileNotFoundError(f"Knowledge corpus not found at {root}")
    chunks: list[Chunk] = []
    for path in sorted(root.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        chunks.extend(_chunks_from_file(path))
    if not chunks:
        raise FileNotFoundError(f"No markdown sections in {root}")
    return chunks


def _chunks_from_file(path: Path) -> list[Chunk]:
    title = path.stem
    section = "Overview"
    buffer: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and title == path.stem:
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            sections.append((section, buffer))
            section = line[3:].strip()
            buffer = []
            continue
        buffer.append(line)
    sections.append((section, buffer))
    source = f"docs/knowledge/{path.name}"
    loaded: list[Chunk] = []
    for name, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        loaded.append(Chunk(doc_id=path.name, title=title[:200], section=name[:200], source_path=source, body=body))
    return loaded


def _embed_text(chunk: Chunk) -> str:
    return f"{chunk.section}\n{chunk.body}"


def reindex(session: Session, embedder: Embedder, root: Path | None = None) -> int:
    chunks = load_chunks(root)
    vectors = embedder.embed([_embed_text(chunk) for chunk in chunks])
    session.execute(delete(KnowledgeChunk))
    for chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            KnowledgeChunk(
                id=uuid.uuid4(),
                doc_id=chunk.doc_id,
                title=chunk.title,
                section=chunk.section,
                source_path=chunk.source_path,
                body=chunk.body,
                embedding=vector,
            )
        )
    session.commit()
    return len(chunks)


def ensure_index(session: Session, embedder: Embedder, root: Path | None = None) -> None:
    """Rebuild when the markdown has changed. Hashing a few dozen sections is cheap."""
    desired = load_chunks(root)
    rows = session.scalars(select(KnowledgeChunk)).all()
    current = {(row.doc_id, row.section): row.body for row in rows}
    wanted = {(chunk.doc_id, chunk.section): chunk.body for chunk in desired}
    if current != wanted or len(rows) != len(desired):
        reindex(session, embedder, root)


def search(session: Session, embedder: Embedder, query: str, k: int = 3) -> list[dict]:
    count = session.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    if count == 0:
        ensure_index(session, embedder)
    rows = session.scalars(select(KnowledgeChunk)).all()
    if not rows:
        return []
    query_vector = embedder.embed([query])[0]
    ranked: list[tuple[float, KnowledgeChunk]] = []
    for row in rows:
        vector = [float(value) for value in row.embedding]
        score = rank_score(query, query_vector, row.section, row.body, vector)
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, row in ranked[:k]:
        results.append(
            {
                "doc": row.doc_id,
                "section": row.section,
                "source": row.source_path,
                "citation": format_citation(row.doc_id, row.section),
                "excerpt": row.body[:700],
                "score": round(score, 4),
            }
        )
    return results
