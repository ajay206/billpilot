"""The hash embedder is deterministic, and policy questions land on the right section."""

from billpilot.agent.embeddings import EMBEDDING_DIM, FakeEmbedder, HashEmbedder, rank_score
from billpilot.agent.knowledge import load_chunks


def test_hash_and_fake_embedders_are_deterministic_and_distinct():
    text = "Goods and services tax is a single line."
    hashed = HashEmbedder().embed([text])[0]
    again = HashEmbedder().embed([text])[0]
    fake = FakeEmbedder().embed([text])[0]
    assert hashed == again
    assert len(hashed) == EMBEDDING_DIM
    assert fake != hashed
    assert abs(sum(value * value for value in hashed) - 1) < 1e-6


def test_policy_questions_rank_the_matching_section_first():
    chunks = load_chunks()
    embedder = HashEmbedder()
    vectors = embedder.embed([f"{chunk.section}\n{chunk.body}" for chunk in chunks])
    questions = [
        ("what is the goods and services tax rate on a bill", "billing-policy.md", "Goods and services tax"),
        ("when does an unpaid bill get a flat late fee", "billing-policy.md", "Late fee"),
        ("who proposes a credit and who approves it", "refunds-and-credits.md", "Who proposes and who approves"),
        ("should the copilot auto-credit a roaming spike", "roaming.md", "Do not auto-credit a roaming spike"),
        ("when is a deposit refunded and is that a bill credit", "deposits.md", "Refunding a deposit"),
        ("when is a number port refused because of a bar or an open dispute", "porting.md", "When a port is refused"),
        (
            "days on the collections ladder from reminder to disconnect",
            "treatment-and-collections.md",
            "The collections ladder",
        ),
        ("does an open dispute hold treatment", "treatment-and-collections.md", "An open dispute holds treatment"),
        (
            "when do voice data and SMS allowances reset on the bill cycle",
            "entitlements.md",
            "Allowances reset on the bill cycle",
        ),
        (
            "value-added service billed when the customer has not opted in",
            "vas-and-plans.md",
            "A value-added service must be opted in",
        ),
        ("numbered steps in the double charge runbook", "csr-runbooks.md", "Double charge"),
        ("numbered steps when an allowance did not reset", "csr-runbooks.md", "Allowance did not reset"),
        (
            "failed autopay that later posted runbook numbered steps",
            "csr-runbooks.md",
            "Failed autopay that later posted",
        ),
        ("is a credit the same thing as a cash refund", "refunds-and-credits.md", "Credit versus a cash refund"),
        ("duplicate charges on a bill what should happen", "refunds-and-credits.md", "Duplicate charges"),
        ("how is a bill calculated from its lines and payments", "billing-policy.md", "How a bill is calculated"),
        ("numbered steps barred after the bill was paid", "csr-runbooks.md", "Barred after the bill was paid"),
    ]
    misses = []
    for query, doc, section in questions:
        query_vector = embedder.embed([query])[0]
        ranked = sorted(
            (
                (
                    rank_score(query, query_vector, chunk.section, chunk.body, vector),
                    chunk,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        winner = ranked[0][1]
        if (winner.doc_id, winner.section) != (doc, section):
            misses.append(f"{query!r} -> {winner.doc_id} § {winner.section}, expected {doc} § {section}")
    assert misses == []
