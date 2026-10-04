"""Operations event store, findings, and report snapshots.

Revision ID: 005_ops
Revises: 004_users
Create Date: 2026-10-04
"""

from pathlib import Path

from alembic import op

revision = "005_ops"
down_revision = "004_users"
branch_labels = None
depends_on = None

_DIR = Path(__file__).resolve().parent


def _strip_comments(chunk: str) -> str:
    lines = [line for line in chunk.splitlines() if line.strip() and not line.strip().startswith("--")]
    return "\n".join(lines).strip()


def _statements(filename: str) -> list[str]:
    script = (_DIR / filename).read_text()
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    index = 0
    while index < len(script):
        char = script[index]
        if char == "'":
            if in_string and index + 1 < len(script) and script[index + 1] == "'":
                current.append("''")
                index += 2
                continue
            in_string = not in_string
            current.append(char)
        elif char == ";" and not in_string:
            statement = _strip_comments("".join(current))
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        index += 1
    tail = _strip_comments("".join(current))
    if tail:
        statements.append(tail)
    return statements


def upgrade() -> None:
    for statement in _statements("005_upgrade.sql"):
        op.execute(statement)


def downgrade() -> None:
    for statement in _statements("005_downgrade.sql"):
        op.execute(statement)
