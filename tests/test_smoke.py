"""Short checks that the main demo flows still work.

Detailed coverage lives in the other test modules. This file only walks the
happy path for login, chat, account lookup, ops reads, and a small onboarding
or migration run.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.main import create_app
from tests.test_migration import purge_phase5
from tests.test_onboarding import _body

ACCOUNTS = "/tmf-api/accountManagement/v4/billingAccount"
OPS_READS = ("/ops/failures", "/ops/reports", "/ops/findings")
DEMO = (
    ("priya.sharma", "demo-priya", "customer"),
    ("ananya.rao", "demo-ananya", "csr"),
    ("meera.kapoor", "demo-meera", "ops"),
)


@pytest.fixture
def client(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def test_each_demo_role_can_sign_in(client: TestClient):
    for username, password, role in DEMO:
        body = _login(client, username, password)
        assert body["role"] == role
        assert client.get("/auth/me").json()["username"] == username
        client.post("/auth/logout", headers={"X-CSRF-Token": body["csrfToken"]})


def test_bad_password_is_rejected(client: TestClient):
    response = client.post("/auth/login", json={"username": "priya.sharma", "password": "wrong"})
    assert response.status_code == 401


def test_customer_chat_returns_an_answer(client: TestClient):
    body = _login(client, "priya.sharma", "demo-priya")
    response = client.post(
        "/agent/chat",
        json={"message": "What is on my latest bill?"},
        headers={"X-CSRF-Token": body["csrfToken"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["refusal"] is False
    assert payload["answer"]


def test_csr_can_look_up_an_account_and_customer_cannot_see_another(client: TestClient, session: Session):
    other = str(
        session.execute(
            text(
                """
                SELECT accounts.id
                FROM accounts
                JOIN customers ON customers.id = accounts.customer_id
                WHERE customers.customer_number = 'CUST-000002'
                """
            )
        ).scalar_one()
    )
    csr = _login(client, "ananya.rao", "demo-ananya")
    found = client.get(ACCOUNTS, params={"q": "CUST-000001"})
    assert found.status_code == 200
    assert found.json()[0]["customerNumber"] == "CUST-000001"
    client.post("/auth/logout", headers={"X-CSRF-Token": csr["csrfToken"]})
    _login(client, "priya.sharma", "demo-priya")
    denied = client.get(f"{ACCOUNTS}/{other}")
    assert denied.status_code == 403


def test_ops_dashboard_reads_are_ops_only(client: TestClient):
    priya = _login(client, "priya.sharma", "demo-priya")
    for path in OPS_READS:
        assert client.get(path).status_code == 403
    client.post("/auth/logout", headers={"X-CSRF-Token": priya["csrfToken"]})
    _login(client, "meera.kapoor", "demo-meera")
    for path in OPS_READS:
        assert client.get(path).status_code == 200


def test_onboarding_and_migration_are_safe_to_repeat(seeded, session: Session):
    del seeded
    purge_phase5(session)
    app = create_app(get_settings())
    ops = {"X-API-Key": "test-ops"}
    with TestClient(app) as client:
        first = client.post("/onboarding", headers=ops, json=_body())
        assert first.status_code == 201, first.text
        again = client.post("/onboarding", headers=ops, json=_body())
        assert again.status_code == 409
        created = client.post("/ops/migration/batches", headers=ops, json={"source": "sample"})
        assert created.status_code == 201, created.text
        batch_id = created.json()["id"]
        assert client.post(f"/ops/migration/batches/{batch_id}/dry-run", headers=ops).status_code == 200
        signed = client.post(
            f"/ops/migration/batches/{batch_id}/sign-off",
            headers=ops,
            json={"approveMapping": True},
        )
        assert signed.status_code == 200
        committed = client.post(f"/ops/migration/batches/{batch_id}/commit", headers=ops)
        assert committed.status_code == 200, committed.text
        second = client.post(f"/ops/migration/batches/{batch_id}/commit", headers=ops)
        assert second.status_code == 200, second.text
        assert second.json()["summary"]["idempotent"] is True
    purge_phase5(session)
