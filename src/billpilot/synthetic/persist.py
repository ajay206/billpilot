"""Replace the synthetic tables with one generated world."""

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from billpilot.models import Base
from billpilot.schema import INSERT_ORDER
from billpilot.synthetic.records import World


def replace_all(session: Session, world: World) -> None:
    table_list = ", ".join(INSERT_ORDER)
    session.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))
    for name in INSERT_ORDER:
        rows = world.rows[name]
        if not rows:
            continue
        table = Base.metadata.tables[name]
        for start in range(0, len(rows), 500):
            session.execute(insert(table), rows[start : start + 500])
    session.commit()
