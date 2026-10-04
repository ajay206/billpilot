"""Postgres-backed tests. They refuse to run against a database that is not a test database."""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://billpilot:billpilot@localhost:5432/billpilot_test",
)
os.environ.setdefault("API_KEY_CUSTOMER", "test-customer")
os.environ.setdefault("API_KEY_CSR", "test-csr")
os.environ.setdefault("API_KEY_OPS", "test-ops")
os.environ.setdefault("CUSTOMER_NUMBER", "CUST-000001")
os.environ.setdefault("CSR_CODE", "CSR-A")
os.environ["RATE_LIMIT_CUSTOMER_PER_MINUTE"] = "10000"
os.environ["RATE_LIMIT_CSR_PER_MINUTE"] = "10000"
os.environ["RATE_LIMIT_OPS_PER_MINUTE"] = "10000"

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.synthetic.config import small_config
from billpilot.synthetic.generate import generate

get_settings.cache_clear()


def _database_url() -> str:
    url = os.environ["DATABASE_URL"]
    name = make_url(url).database or ""
    if not name.startswith("billpilot_test"):
        pytest.exit(
            f"Refusing to run tests against database {name!r}. Use a name starting with billpilot_test.",
            returncode=1,
        )
    return url


def _alembic(direction: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))
    if direction == "upgrade":
        command.upgrade(config, "head")
    else:
        command.downgrade(config, "base")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _database_url()
    eng = create_engine(url, pool_pre_ping=True)
    try:
        with eng.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.exit(
            f"PostgreSQL is not reachable ({exc}). Start it with: docker compose up -d postgres",
            returncode=1,
        )
    _alembic("upgrade")
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def seeded(engine: Engine) -> Engine:
    with Session(engine) as session:
        generate(small_config(), session=session)
    return engine


@pytest.fixture
def session(seeded: Engine) -> Iterator[Session]:
    with Session(seeded) as db:
        yield db
