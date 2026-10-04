"""Dry run, reconciliation, idempotent commit, rollback, and reject reasons."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.main import create_app
from billpilot.migration.legacy import render_csv, sample_records
from billpilot.migration.mapping import load_plan_map

OPS = {"X-API-Key": "test-ops"}
CSR = {"X-API-Key": "test-csr"}
CUSTOMER = {"X-API-Key": "test-customer"}

EXPECTED_REASONS = {
    "bad_msisdn": 1,
    "duplicate_msisdn": 1,
    "unknown_plan": 1,
    "negative_balance": 1,
    "duplicate_customer": 1,
    "orphan_service": 1,
    "orphan_balance": 1,
}


def purge_phase5(session: Session) -> None:
    """Remove subscribers this phase created so later tests still see the seed."""
    session.rollback()
    session.execute(text("DELETE FROM migration_links"))
    session.execute(text("DELETE FROM migration_records"))
    session.execute(text("DELETE FROM migration_batches"))
    where = "c.customer_number LIKE 'ONB-%' OR c.customer_number LIKE 'MIG-%'"
    session.execute(
        text(
            f"""
            DELETE FROM invoice_lines WHERE invoice_id IN (
                SELECT i.id FROM invoices i
                JOIN accounts a ON a.id = i.account_id
                JOIN customers c ON c.id = a.customer_id
                WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            DELETE FROM invoices WHERE account_id IN (
                SELECT a.id FROM accounts a JOIN customers c ON c.id = a.customer_id WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            DELETE FROM entitlement_balances WHERE entitlement_id IN (
                SELECT e.id FROM entitlements e
                JOIN subscriptions s ON s.id = e.subscription_id
                JOIN accounts a ON a.id = s.account_id
                JOIN customers c ON c.id = a.customer_id
                WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            DELETE FROM entitlements WHERE subscription_id IN (
                SELECT s.id FROM subscriptions s
                JOIN accounts a ON a.id = s.account_id
                JOIN customers c ON c.id = a.customer_id
                WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            DELETE FROM vas_subscriptions WHERE subscription_id IN (
                SELECT s.id FROM subscriptions s
                JOIN accounts a ON a.id = s.account_id
                JOIN customers c ON c.id = a.customer_id
                WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            DELETE FROM account_treatment WHERE account_id IN (
                SELECT a.id FROM accounts a JOIN customers c ON c.id = a.customer_id WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            DELETE FROM credit_profiles WHERE account_id IN (
                SELECT a.id FROM accounts a JOIN customers c ON c.id = a.customer_id WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            DELETE FROM subscriptions WHERE account_id IN (
                SELECT a.id FROM accounts a JOIN customers c ON c.id = a.customer_id WHERE {where}
            )
            """
        )
    )
    session.execute(
        text(
            """
            DELETE FROM accounts WHERE customer_id IN (
                SELECT id FROM customers WHERE customer_number LIKE 'ONB-%' OR customer_number LIKE 'MIG-%'
            )
            """
        )
    )
    session.execute(text("DELETE FROM customers WHERE customer_number LIKE 'ONB-%' OR customer_number LIKE 'MIG-%'"))
    session.commit()


def _customers(session: Session) -> int:
    return int(session.scalar(text("SELECT COUNT(*) FROM customers WHERE customer_number LIKE 'MIG-%'")) or 0)


def _opening_total(session: Session) -> Decimal:
    total = session.scalar(
        text(
            """
            SELECT COALESCE(SUM(i.amount_due), 0)
            FROM invoices i
            JOIN accounts a ON a.id = i.account_id
            JOIN customers c ON c.id = a.customer_id
            WHERE c.customer_number LIKE 'MIG-%'
            """
        )
    )
    return Decimal(total)


def test_plan_map_is_config_and_does_not_guess(seeded):
    del seeded
    load_plan_map.cache_clear()
    plan_map = load_plan_map()
    assert plan_map.version == "2026-10-04"
    assert plan_map.suggest("LEG-SMART").target_code == "SMART-199"
    assert plan_map.suggest("leg-plus").target_code == "PLUS-399"
    assert plan_map.suggest("LEG-GONE") is None


def test_dry_run_reconciles_without_writing_and_names_every_reject(seeded, session: Session):
    del seeded
    purge_phase5(session)
    before = _customers(session)
    app = create_app(get_settings())
    with TestClient(app) as client:
        denied = client.post("/ops/migration/batches", headers=CUSTOMER, json={"source": "sample"})
        assert denied.status_code == 403
        created = client.post("/ops/migration/batches", headers=OPS, json={"source": "sample"})
        assert created.status_code == 201, created.text
        batch_id = created.json()["id"]
        assert _customers(session) == before
        dry = client.post(f"/ops/migration/batches/{batch_id}/dry-run", headers=OPS)
        assert dry.status_code == 200, dry.text
        body = dry.json()
    assert _customers(session) == before
    summary = body["summary"]
    assert body["status"] == "dry_run"
    assert summary["writes"] == 0
    assert summary["source"]["records"] == 26
    assert summary["source"]["customers"] == 9
    assert summary["source"]["services"] == 9
    assert summary["source"]["balances"] == 8
    assert summary["source"]["balanceTotal"] == "705.00"
    assert summary["target"]["customers"] == 4
    assert summary["target"]["services"] == 4
    assert summary["target"]["balances"] == 4
    assert summary["target"]["balanceTotal"] == "650.50"
    assert summary["acceptedBalanceTotal"] == "650.50"
    assert summary["balanceMatched"] is True
    assert summary["rejected"] == 7
    assert summary["skipped"] == 7
    assert summary["byReason"] == EXPECTED_REASONS
    suggestions = {row["legacyCode"]: row for row in summary["mappingSuggestions"]}
    assert suggestions["LEG-SMART"]["targetCode"] == "SMART-199"
    assert suggestions["LEG-SMART"]["rationale"]
    assert suggestions["LEG-GONE"]["targetCode"] is None
    reasons = {row["reason"] for row in body["records"] if row["status"] == "rejected"}
    assert reasons == set(EXPECTED_REASONS)
    assert "bad_msisdn" in body["csv"]
    assert "650.50" in body["csv"]
    purge_phase5(session)


def test_commit_is_idempotent_and_rollback_restores_the_ledger(seeded, session: Session):
    del seeded
    purge_phase5(session)
    before = int(session.scalar(text("SELECT COUNT(*) FROM customers")) or 0)
    app = create_app(get_settings())
    with TestClient(app) as client:
        created = client.post(
            "/ops/migration/batches",
            headers=OPS,
            json={"source": "csv", "name": "legacy.csv", "body": render_csv(sample_records())},
        )
        assert created.status_code == 201, created.text
        batch_id = created.json()["id"]
        early = client.post(f"/ops/migration/batches/{batch_id}/commit", headers=OPS)
        assert early.status_code == 409
        assert client.post(f"/ops/migration/batches/{batch_id}/dry-run", headers=OPS).status_code == 200
        refused = client.post(
            f"/ops/migration/batches/{batch_id}/sign-off",
            headers=OPS,
            json={"approveMapping": False},
        )
        assert refused.status_code == 422
        csr = client.post(
            f"/ops/migration/batches/{batch_id}/sign-off",
            headers=CSR,
            json={"approveMapping": True},
        )
        assert csr.status_code == 403
        signed = client.post(
            f"/ops/migration/batches/{batch_id}/sign-off",
            headers=OPS,
            json={"approveMapping": True},
        )
        assert signed.status_code == 200
        committed = client.post(f"/ops/migration/batches/{batch_id}/commit", headers=OPS)
        assert committed.status_code == 200, committed.text
        again = client.post(f"/ops/migration/batches/{batch_id}/commit", headers=OPS)
        assert again.status_code == 200, again.text
        assert again.json()["summary"]["idempotent"] is True
        assert again.json()["summary"]["writes"] == 0
        health = client.get("/health")
        assert health.status_code == 200
        bills = client.get("/tmf-api/customerBillManagement/v4/customerBill?limit=1", headers=OPS)
        assert bills.status_code == 200
        csv_body = client.get(f"/ops/migration/batches/{batch_id}/reconciliation.csv", headers=OPS)
        assert csv_body.status_code == 200
        assert "text/csv" in csv_body.headers["content-type"]
        assert "bad_msisdn" in csv_body.text
        session.expire_all()
        assert _customers(session) == 4
        assert int(session.scalar(text("SELECT COUNT(*) FROM customers")) or 0) == before + 4
        assert _opening_total(session) == Decimal("650.50")
        assert session.scalar(text("SELECT COUNT(*) FROM subscriptions WHERE msisdn = '9810001001'")) == 1
        entitlements = session.scalar(
            text(
                """
                SELECT COUNT(*) FROM entitlements e
                JOIN subscriptions s ON s.id = e.subscription_id
                JOIN accounts a ON a.id = s.account_id
                JOIN customers c ON c.id = a.customer_id
                WHERE c.customer_number LIKE 'MIG-%' AND e.status = 'active'
                """
            )
        )
        assert entitlements == 12
        vas = session.scalar(
            text(
                """
                SELECT COUNT(*) FROM vas_subscriptions v
                JOIN subscriptions s ON s.id = v.subscription_id
                WHERE v.product_code = 'CALLER-TUNE' AND v.opted_in IS TRUE
                  AND s.msisdn = '9810001002'
                """
            )
        )
        assert vas == 1
        treatment = session.scalar(
            text(
                """
                SELECT COUNT(*) FROM account_treatment t
                JOIN accounts a ON a.id = t.account_id
                JOIN customers c ON c.id = a.customer_id
                WHERE c.customer_number LIKE 'MIG-%' AND t.stage = 'none' AND t.status = 'active'
                """
            )
        )
        assert treatment == 4
        rolled = client.post(f"/ops/migration/batches/{batch_id}/rollback", headers=OPS)
        assert rolled.status_code == 200, rolled.text
        assert rolled.json()["status"] == "rolled_back"
        assert rolled.json()["summary"]["restored"] is True
        session.expire_all()
        assert _customers(session) == 0
        assert _opening_total(session) == Decimal("0")
        assert int(session.scalar(text("SELECT COUNT(*) FROM customers")) or 0) == before
        second = client.post(f"/ops/migration/batches/{batch_id}/rollback", headers=OPS)
        assert second.status_code == 200
        assert second.json()["summary"]["alreadyRolledBack"] is True
        session.expire_all()
        assert _customers(session) == 0
    purge_phase5(session)


def test_a_failed_commit_does_not_leave_a_partial_batch(seeded, session: Session, monkeypatch):
    del seeded
    purge_phase5(session)
    before = _customers(session)
    app = create_app(get_settings())
    real = __import__("billpilot.migration.pipeline", fromlist=["insert_group"]).insert_group
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("stop after the first subscriber")
        return real(*args, **kwargs)

    monkeypatch.setattr("billpilot.migration.pipeline.insert_group", flaky)
    with TestClient(app, raise_server_exceptions=True) as client:
        created = client.post("/ops/migration/batches", headers=OPS, json={"source": "sample"})
        batch_id = created.json()["id"]
        assert client.post(f"/ops/migration/batches/{batch_id}/dry-run", headers=OPS).status_code == 200
        assert (
            client.post(
                f"/ops/migration/batches/{batch_id}/sign-off",
                headers=OPS,
                json={"approveMapping": True},
            ).status_code
            == 200
        )
        try:
            client.post(f"/ops/migration/batches/{batch_id}/commit", headers=OPS)
            raised = False
        except RuntimeError:
            raised = True
        assert raised
    session.expire_all()
    assert _customers(session) == before
    status = session.scalar(text("SELECT status FROM migration_batches WHERE id = :id"), {"id": batch_id})
    assert status == "signed_off"
    purge_phase5(session)
