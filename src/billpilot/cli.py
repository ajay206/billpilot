"""Migrate and seed from the command line.

`migrate-and-seed` is what Docker runs once Postgres is healthy. Seeding replaces
the synthetic tables; it does not touch alembic_version.
"""

import argparse
import json
import sys
import time
import uuid
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


def ledger_customer_count(url: str) -> int | None:
    """How many customers are loaded. None means the table is not there yet."""
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            exists = connection.execute(text("SELECT to_regclass('public.customers')")).scalar()
            if exists is None:
                return None
            return int(connection.execute(text("SELECT COUNT(*) FROM customers")).scalar() or 0)
    finally:
        engine.dispose()


def seed_if_empty() -> None:
    """Migrate must already have run. A populated ledger is left alone.

    The hosted container has no separate seed job, so the first boot fills an
    empty database. A later boot, and `docker compose up` after the seed
    service, finds the rows and returns.
    """
    settings = get_settings()
    _wait_for_database(settings.database_url)
    count = ledger_customer_count(settings.database_url)
    if count is None:
        raise SystemExit("The customers table is missing. Run `billpilot migrate` first.")
    if count:
        print(f"Ledger already has {count} customers. Skipping seed.")
        return
    print("Ledger is empty. Seeding synthetic customers.")
    seed(config_from_env(), Path(settings.ground_truth_path))


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


def _ask(args) -> None:
    import httpx
    from sqlalchemy.orm import Session

    from billpilot.agent.loop import run_agent
    from billpilot.agent.model import build_model
    from billpilot.agent.tools import BssClient
    from billpilot.api.security import principal_for_key

    settings = get_settings()
    if args.backend:
        settings = settings.model_copy(update={"llm_backend": args.backend})
    keys = {
        "customer": settings.api_key_customer,
        "csr": settings.api_key_csr,
        "ops": settings.api_key_ops,
    }
    key = keys[args.persona]
    principal = principal_for_key(settings, key)
    _wait_for_database(settings.database_url)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    bss = BssClient(settings.bss_base_url, key)
    try:
        with Session(engine) as session:
            result = run_agent(
                message=args.message,
                persona=principal.role,
                actor_id=principal.actor_id,
                bss=bss,
                model=build_model(settings),
                session=session,
                request_id=str(uuid.uuid4()),
                settings=settings,
                account_id=args.account,
                customer_number=principal.customer_number,
            )
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"The mock BSS at {settings.bss_base_url} did not answer ({exc}). Start it with: docker compose up"
        ) from exc
    finally:
        bss.close()
        engine.dispose()
    print(result.answer)
    if result.citations:
        print("Citations:")
        for citation in result.citations:
            print(f"- {citation['doc']} § {citation['section']}")
    if result.proposed_actions:
        print("Proposed:")
        for action in result.proposed_actions:
            print(f"- {action.get('type')} {action.get('status')} {action.get('amount', '')}".rstrip())
    print(
        f"run={result.run_id} model={result.model} tokens={result.prompt_tokens}+{result.completion_tokens} "
        f"estimated_cost_usd={result.estimated_cost_usd} latency_ms={result.latency_ms}"
    )


def _reindex_knowledge() -> None:
    from sqlalchemy.orm import Session

    from billpilot.agent.embeddings import build_embedder
    from billpilot.agent.knowledge import reindex

    settings = get_settings()
    _wait_for_database(settings.database_url)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with Session(engine) as session:
        count = reindex(session, build_embedder(settings))
    engine.dispose()
    print(f"Indexed {count} policy sections.")


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
    commands.add_parser("seed-if-empty")
    ask = commands.add_parser("ask", help="Ask the copilot. The mock BSS must already be running.")
    ask.add_argument("--persona", required=True, choices=("customer", "csr", "ops"))
    ask.add_argument("--account", help="Billing account UUID. Required for a CSR or ops investigation.")
    ask.add_argument("--backend", choices=("fake", "api"), help="Override LLM_BACKEND for this process.")
    ask.add_argument("message")
    knowledge = commands.add_parser("knowledge")
    knowledge_commands = knowledge.add_subparsers(dest="knowledge_command", required=True)
    knowledge_commands.add_parser("reindex")
    args = parser.parse_args(argv)

    if args.command == "migrate":
        _alembic("upgrade")
        return
    if args.command == "downgrade":
        _alembic("downgrade")
        return
    if args.command == "ask":
        _ask(args)
        return
    if args.command == "seed-if-empty":
        seed_if_empty()
        return
    if args.command == "knowledge":
        _reindex_knowledge()
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
