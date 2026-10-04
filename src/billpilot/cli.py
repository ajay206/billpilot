"""Migrate and seed from the command line.

`migrate-and-seed` is what Docker runs once Postgres is healthy. Seeding replaces
the synthetic tables; it does not touch alembic_version.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.synthetic.config import DEFAULT_ANOMALY_COUNTS, GeneratorConfig
from billpilot.synthetic.generate import generate


def _wait_for_database(url: str, attempts: int = 30) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            engine.dispose()
            return
        except Exception as exc:  # the database may still be starting
            last_error = exc
            time.sleep(1)
    raise SystemExit(f"Database not ready: {last_error}")


def _alembic(direction: str) -> None:
    settings = get_settings()
    _wait_for_database(settings.database_url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    if direction == "upgrade":
        command.upgrade(config, "head")
    else:
        command.downgrade(config, "base")


def config_from_env() -> GeneratorConfig:
    settings = get_settings()
    counts = dict(DEFAULT_ANOMALY_COUNTS)
    if settings.anomaly_counts.strip():
        overrides = json.loads(settings.anomaly_counts)
        counts.update({key: int(value) for key, value in overrides.items()})
    return GeneratorConfig(
        seed=settings.seed,
        customer_count=settings.customer_count,
        months=settings.months,
        anomaly_counts=counts,
    )


def seed(config: GeneratorConfig, output: Path) -> None:
    settings = get_settings()
    _wait_for_database(settings.database_url)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with Session(engine) as session:
        _world, document = generate(config, session=session, output_path=output)
    engine.dispose()
    counts = document["anomaly_counts"]
    print(f"Seeded {document['customer_count']} customers as of {document['as_of']} ({document['currency']}).")
    print(f"Planted {sum(counts.values())} anomalies across {len(counts)} types.")
    print(f"Ground truth: {output}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="billpilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser("downgrade")
    seed_parser = commands.add_parser("seed")
    seed_parser.add_argument("--customers", type=int)
    seed_parser.add_argument("--months", type=int)
    seed_parser.add_argument("--seed", type=int)
    seed_parser.add_argument("--output")
    both = commands.add_parser("migrate-and-seed")
    both.add_argument("--customers", type=int)
    both.add_argument("--months", type=int)
    both.add_argument("--seed", type=int)
    both.add_argument("--output")
    args = parser.parse_args(argv)

    if args.command == "migrate":
        _alembic("upgrade")
        return
    if args.command == "downgrade":
        _alembic("downgrade")
        return

    config = config_from_env()
    if getattr(args, "customers", None) is not None:
        config.customer_count = args.customers
    if getattr(args, "months", None) is not None:
        config.months = args.months
    if getattr(args, "seed", None) is not None:
        config.seed = args.seed
    output = Path(getattr(args, "output", None) or get_settings().ground_truth_path)
    if args.command == "migrate-and-seed":
        _alembic("upgrade")
    seed(config, output)


if __name__ == "__main__":
    sys.exit(main())
