"""Sign-in, session scope, and the role matrix. API keys stay available for the CLI."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.auth.demo import DEMO_USERS, align_demo_holders, ensure_demo_users
from billpilot.auth.session import read_session, sign_session
from billpilot.auth.throttle import FailureLimiter
from billpilot.config import get_settings
from billpilot.main import create_app

BILLS = "/tmf-api/customerBillManagement/v4/customerBill"
DISPUTES = "/tmf-api/customerBillManagement/v4/customerBillDispute"
ADJUSTMENTS = "/tmf-api/customerBillManagement/v4/billAdjustment"
TICKETS = "/tmf-api/troubleTicket/v4/troubleTicket"
OFFERINGS = "/tmf-api/productCatalogManagement/v4/productOffering"
AUDIT = "/ops/auditLog"
RUNS = "/ops/agentRuns"

PASSWORDS = {item.username: item.password for item in DEMO_USERS}


@pytest.fixture
def client(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as test_client:
        yield test_client


def _account(session: Session, customer_number: str) -> str:
    return str(
        session.execute(
            text(
                """
                SELECT accounts.id
                FROM accounts
                JOIN customers ON customers.id = accounts.customer_id
                WHERE customers.customer_number = :number
                """
            ),
            {"number": customer_number},
        ).scalar_one()
    )


def _bill(session: Session, account_id: str) -> str:
    return str(
        session.execute(
            text("SELECT id FROM invoices WHERE account_id = :account ORDER BY issue_date DESC LIMIT 1"),
            {"account": account_id},
        ).scalar_one()
    )


def _sign_in(client: TestClient, username: str) -> dict:
    response = client.post("/auth/login", json={"username": username, "password": PASSWORDS[username]})
    assert response.status_code == 200, response.text
    return response.json()


def _csrf(body: dict) -> dict[str, str]:
    return {"X-CSRF-Token": body["csrfToken"]}


def test_session_token_is_signed_and_expires():
    secret = "dev-session-secret"
    token = sign_session("user-1", "csrf-1", secret, 60, now=1_000)
    assert read_session(token, secret, now=1_050) == {"uid": "user-1", "csrf": "csrf-1", "exp": 1_060}
    assert read_session(token, "another-session-secret", now=1_050) is None
    assert read_session(token + "x", secret, now=1_050) is None
    assert read_session(token, secret, now=1_060) is None


def test_failure_limiter_window_expires():
    clock = {"now": 0.0}
    limiter = FailureLimiter(2, 10, clock=lambda: clock["now"])
    limiter.record("user:a")
    limiter.record("user:a")
    assert limiter.blocked("user:a")
    limiter.reset("user:a")
    assert not limiter.blocked("user:a")
    limiter.record("user:a")
    limiter.record("user:a")
    clock["now"] = 11
    assert not limiter.blocked("user:a")


def test_demo_accounts_are_public_and_marked_demo_only(client: TestClient):
    response = client.get("/auth/demo-accounts")
    assert response.status_code == 200
    rows = response.json()
    assert [row["username"] for row in rows] == [item.username for item in DEMO_USERS]
    assert all(row["demoOnly"] is True and row["password"] for row in rows)
    roles = {row["role"] for row in rows}
    assert roles == {"customer", "csr", "ops"}


def test_ensure_demo_users_does_not_duplicate(session: Session):
    assert ensure_demo_users(session) == 0
    count = session.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
    assert count == len(DEMO_USERS)


def test_demo_holder_names_match_sign_in_and_realign(session: Session):
    holders = session.execute(
        text(
            "SELECT customer_number, given_name, family_name FROM customers "
            "WHERE customer_number IN ('CUST-000001', 'CUST-000002', 'CUST-000003', 'CUST-000005') "
            "ORDER BY customer_number"
        )
    ).all()
    by_number = {row.customer_number: (row.given_name, row.family_name) for row in holders}
    assert by_number["CUST-000001"] == ("Priya", "Sharma")
    assert by_number["CUST-000003"] == ("Arjun", "Mehta")
    assert by_number["CUST-000005"] == ("Neha", "Iyer")
    neighbour = by_number["CUST-000002"]
    session.execute(
        text("UPDATE customers SET given_name = 'Isaac', family_name = 'Bakshi' WHERE customer_number = 'CUST-000001'")
    )
    session.commit()
    assert align_demo_holders(session) == 1
    session.commit()
    restored = session.execute(
        text("SELECT given_name, family_name FROM customers WHERE customer_number = 'CUST-000001'")
    ).one()
    assert (restored.given_name, restored.family_name) == ("Priya", "Sharma")
    untouched = session.execute(
        text("SELECT given_name, family_name FROM customers WHERE customer_number = 'CUST-000002'")
    ).one()
    assert (untouched.given_name, untouched.family_name) == neighbour
    assert align_demo_holders(session) == 0


def test_login_sets_an_httponly_cookie_and_audits(client: TestClient, session: Session):
    response = client.post("/auth/login", json={"username": "Priya.Sharma", "password": "demo-priya"})
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "customer"
    assert body["customerNumber"] == "CUST-000001"
    assert body["displayName"] == "Priya Sharma"
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith("bp_session="))
    csrf_cookie = next(value for value in cookies if value.startswith("bp_csrf="))
    assert "httponly" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "priya.sharma"
    logins = session.execute(
        text("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.login' AND actor_id = 'user:priya.sharma'")
    ).scalar_one()
    assert logins >= 1


def test_unknown_user_and_bad_password_look_the_same(client: TestClient, session: Session):
    unknown = client.post("/auth/login", json={"username": "nobody", "password": "nope"})
    wrong = client.post("/auth/login", json={"username": "priya.sharma", "password": "nope"})
    assert unknown.status_code == 401
    assert wrong.status_code == 401
    assert unknown.json()["message"] == wrong.json()["message"] == "Unknown username or password."
    reasons = set(
        session.execute(text("SELECT payload->>'reason' FROM audit_log WHERE action = 'auth.login_failed'")).scalars()
    )
    assert reasons == {"unknown_user", "bad_password"}


def test_failed_logins_are_rate_limited(seeded, session: Session):
    del seeded
    settings = get_settings().model_copy(update={"login_failure_limit": 3})
    app = create_app(settings)
    with TestClient(app) as client:
        for _ in range(3):
            failed = client.post("/auth/login", json={"username": "priya.sharma", "password": "nope"})
            assert failed.status_code == 401
        blocked = client.post("/auth/login", json={"username": "priya.sharma", "password": "demo-priya"})
    assert blocked.status_code == 429
    assert blocked.json()["message"] == "Too many sign-in attempts. Try again later."
    assert blocked.headers["Retry-After"] == "60"
    limited = session.execute(
        text("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.login_rate_limited'")
    ).scalar_one()
    assert limited >= 1


def test_logout_clears_the_session_and_is_audited(client: TestClient, session: Session):
    body = _sign_in(client, "meera.kapoor")
    gone = client.post("/auth/logout", headers=_csrf(body))
    assert gone.status_code == 204
    assert client.get("/auth/me").status_code == 401
    logouts = session.execute(
        text("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.logout' AND actor_id = 'user:meera.kapoor'")
    ).scalar_one()
    assert logouts >= 1


def test_cookie_writes_require_csrf_and_reject_a_foreign_origin(client: TestClient, session: Session):
    body = _sign_in(client, "priya.sharma")
    account_id = _account(session, "CUST-000001")
    payload = {
        "billingAccount": {"id": account_id},
        "category": "billing",
        "description": "Please explain this charge.",
    }
    missing = client.post(DISPUTES, json=payload)
    assert missing.status_code == 403
    foreign = client.post(
        DISPUTES,
        json=payload,
        headers={**_csrf(body), "Origin": "https://evil.example"},
    )
    assert foreign.status_code == 403
    created = client.post(DISPUTES, json=payload, headers=_csrf(body))
    assert created.status_code == 201


def test_expired_session_is_rejected(client: TestClient, session: Session):
    user_id = session.execute(text("SELECT id FROM users WHERE username = 'priya.sharma'")).scalar_one()
    token = sign_session(str(user_id), "csrf-old", get_settings().session_secret, 30, now=1_000)
    client.cookies.set("bp_session", token)
    assert client.get("/auth/me").status_code == 401


def test_api_keys_still_authenticate_service_calls(client: TestClient):
    assert client.get(BILLS, headers={"X-API-Key": "test-customer"}).status_code == 200
    assert client.get(AUDIT, headers={"X-API-Key": "test-ops"}).status_code == 200
    assert client.get(BILLS).status_code == 401


@pytest.mark.parametrize(
    ("username", "path", "expected"),
    [
        ("priya.sharma", AUDIT, 403),
        ("ananya.rao", AUDIT, 403),
        ("meera.kapoor", AUDIT, 200),
        ("priya.sharma", RUNS, 403),
        ("ananya.rao", RUNS, 403),
        ("meera.kapoor", RUNS, 200),
        ("priya.sharma", OFFERINGS, 200),
        ("ananya.rao", OFFERINGS, 200),
        ("meera.kapoor", OFFERINGS, 200),
        ("priya.sharma", BILLS, 200),
        ("ananya.rao", BILLS, 200),
        ("meera.kapoor", BILLS, 200),
    ],
)
def test_role_matrix_for_reads(client: TestClient, username: str, path: str, expected: int):
    _sign_in(client, username)
    assert client.get(path).status_code == expected


def test_scope_matrix_for_accounts_and_writes(client: TestClient, session: Session):
    own = _account(session, "CUST-000001")
    other = _account(session, "CUST-000002")
    bill_id = _bill(session, own)

    priya = _sign_in(client, "priya.sharma")
    assert client.get(BILLS, params={"billingAccount.id": own}).status_code == 200
    assert client.get(BILLS, params={"billingAccount.id": other}).status_code == 403
    assert client.get(f"/tmf-api/accountManagement/v4/billingAccount/{other}").status_code == 403
    adjustment = {
        "billingAccount": {"id": own},
        "customerBill": {"id": bill_id},
        "adjustmentType": "credit",
        "amount": {"unit": "INR", "value": "1.00"},
        "reason": "A customer cannot propose a credit.",
    }
    assert client.post(ADJUSTMENTS, json=adjustment, headers=_csrf(priya)).status_code == 403
    assert (
        client.post(
            TICKETS,
            json={"billingAccount": {"id": own}, "name": "No", "description": "Customers do not open tickets."},
            headers=_csrf(priya),
        ).status_code
        == 403
    )

    _sign_in(client, "vikram.nair")
    assert client.get(BILLS, params={"billingAccount.id": own}).status_code == 403
    assert client.get(BILLS, params={"billingAccount.id": other}).status_code == 200

    ananya = _sign_in(client, "ananya.rao")
    assert client.get(BILLS, params={"billingAccount.id": own}).status_code == 200
    assert client.get(BILLS, params={"billingAccount.id": other}).status_code == 403
    proposed = client.post(ADJUSTMENTS, json=adjustment, headers=_csrf(ananya))
    assert proposed.status_code == 201
    assert proposed.json()["status"] == "pending_approval"
    approve_url = f"{ADJUSTMENTS}/{proposed.json()['id']}/approve"
    assert client.post(approve_url, json={"decision": "approve"}, headers=_csrf(ananya)).status_code == 403

    meera = _sign_in(client, "meera.kapoor")
    assert client.get(BILLS, params={"billingAccount.id": own}).status_code == 200
    assert client.get(BILLS, params={"billingAccount.id": other}).status_code == 200
    assert client.post(ADJUSTMENTS, json=adjustment, headers=_csrf(meera)).status_code == 403
    applied = client.post(approve_url, json={"decision": "approve", "note": "Ops approves."}, headers=_csrf(meera))
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert (
        client.post(
            TICKETS,
            json={"billingAccount": {"id": own}, "name": "No", "description": "Ops does not open tickets."},
            headers=_csrf(meera),
        ).status_code
        == 403
    )


def test_agent_uses_the_session_role_and_refuses_another_account(client: TestClient, session: Session):
    priya = _sign_in(client, "priya.sharma")
    other = _account(session, "CUST-000002")
    denied = client.post(
        "/agent/chat",
        json={"message": "Explain the latest bill.", "accountId": other, "role": "ops"},
        headers=_csrf(priya),
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/agent/chat",
        json={
            "message": "Explain the latest bill line by line and compare it with the previous month and the tariff.",
            "role": "ops",
        },
        headers=_csrf(priya),
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["refusal"] is False
    assert "list_bills" in [call["name"] for call in body["toolCalls"]]
    stored = session.execute(
        text("SELECT persona, actor_id FROM agent_runs WHERE id = :id"),
        {"id": body["runId"]},
    ).one()
    assert stored.persona == "customer"
    assert stored.actor_id == "user:priya.sharma"

    ananya = _sign_in(client, "ananya.rao")
    csr_denied = client.post(
        "/agent/chat",
        json={"message": "Look at this account.", "accountId": other},
        headers=_csrf(ananya),
    )
    assert csr_denied.status_code == 403
    assert client.get(RUNS).status_code == 403


def test_frontend_source_does_not_embed_api_keys():
    root = Path("web/src")
    text_blob = "\n".join(path.read_text() for path in root.rglob("*") if path.suffix in {".ts", ".tsx"})
    for secret in ("dev-customer-key", "dev-csr-key", "dev-ops-key", "X-API-Key"):
        assert secret not in text_blob
