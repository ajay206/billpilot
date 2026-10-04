"""Every labelled fault in ground truth is present in the seeded database."""

from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.anomaly_checks import CHECKERS, check_anomaly, check_controls

from billpilot.schema import TABLES
from billpilot.synthetic.config import ANOMALY_TYPES, small_config
from billpilot.synthetic.generate import build_world


def _load(session: Session) -> dict[str, list[dict]]:
    loaded = {}
    for table in TABLES:
        rows = session.execute(text(f"SELECT * FROM {table}")).mappings().all()
        loaded[table] = [dict(row) for row in rows]
    return loaded


def test_every_planted_anomaly_matches_ground_truth(session: Session):
    world = build_world(small_config())
    tables = _load(session)
    document = world.ground_truth
    assert {row["type"] for row in document["anomalies"]} == set(ANOMALY_TYPES)
    assert set(CHECKERS) == set(ANOMALY_TYPES)
    errors = []
    for anomaly in document["anomalies"]:
        errors.extend(check_anomaly(tables, anomaly))
    errors.extend(check_controls(tables, document["controls"]))
    assert errors == []
