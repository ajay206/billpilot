"""The generator is deterministic and the default counts stay part of the contract."""

from billpilot.synthetic.build import build_world, world_signature
from billpilot.synthetic.config import (
    ANOMALY_TYPES,
    DEFAULT_ANOMALY_COUNTS,
    GeneratorConfig,
    small_config,
)
from billpilot.synthetic.generate import generate


def test_default_counts_cover_every_type_and_sum_to_92():
    assert set(DEFAULT_ANOMALY_COUNTS) == set(ANOMALY_TYPES)
    assert sum(DEFAULT_ANOMALY_COUNTS.values()) == 92
    GeneratorConfig().validate()


def test_the_same_seed_builds_the_same_world():
    first = world_signature(build_world(small_config()))
    second = world_signature(build_world(small_config()))
    assert first == second


def test_a_different_seed_changes_the_world():
    changed = small_config()
    changed.seed = 99
    assert world_signature(build_world(small_config())) != world_signature(build_world(changed))


def test_reseeding_replaces_rows_with_the_same_ids(engine):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    config = small_config()
    with Session(engine) as session:
        first, document = generate(config, session=session)
    first_ids = [str(row["id"]) for row in first.rows["customers"]]
    with Session(engine) as session:
        second, again = generate(config, session=session)
    second_ids = [str(row["id"]) for row in second.rows["customers"]]
    assert first_ids == second_ids
    assert document == again
    assert len(document["anomalies"]) == len(ANOMALY_TYPES)
    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM customers")).scalar()
    assert count == config.customer_count
