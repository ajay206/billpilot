"""The migration creates the 23 billing tables, and the ORM matches those columns."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from billpilot.models import Base
from billpilot.schema import INSERT_ORDER, TABLES
from billpilot.synthetic.config import small_config
from billpilot.synthetic.generate import generate
from tests.conftest import _alembic


def test_migration_creates_every_table(engine):
    names = set(inspect(engine).get_table_names())
    assert set(TABLES) <= names
    assert "users" in names
    assert len(TABLES) == 23
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "004_users"


def test_orm_columns_match_the_migration(engine):
    inspector = inspect(engine)
    for model in Base.registry.mappers:
        table = model.local_table.name
        db_columns = {column["name"] for column in inspector.get_columns(table)}
        orm_columns = {column.name for column in model.columns}
        assert orm_columns == db_columns, table


def test_insert_order_covers_every_table():
    assert set(INSERT_ORDER) == set(TABLES)


def test_currency_must_be_inr(session: Session):
    customer_id = session.execute(text("SELECT id FROM customers LIMIT 1")).scalar()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO accounts (
                    id, customer_id, account_number, status, currency,
                    billing_cycle_day, assigned_csr, opened_at, created_at
                ) VALUES (
                    gen_random_uuid(), :customer_id, 'ACC-BAD', 'active', 'USD',
                    1, 'CSR-A', now(), now()
                )
                """
            ),
            {"customer_id": customer_id},
        )
        session.commit()
    session.rollback()


def test_phone_must_use_the_india_prefix(session: Session):
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO customers (
                    id, customer_number, given_name, family_name, email, phone, city, state, created_at
                ) VALUES (
                    gen_random_uuid(), 'CUST-BAD', 'A', 'B', 'bad@example.com',
                    '+10000000000', 'Mumbai', 'Maharashtra', now()
                )
                """
            )
        )
        session.commit()
    session.rollback()


def test_downgrade_removes_tables_and_upgrade_restores_them(engine):
    _alembic("downgrade")
    try:
        names = set(inspect(engine).get_table_names())
        assert "customers" not in names
        assert "invoices" not in names
    finally:
        _alembic("upgrade")
        with Session(engine) as session:
            generate(small_config(), session=session)
        names = set(inspect(engine).get_table_names())
        assert set(TABLES) <= names
