"""Contract, persona scope, and the adjustment approval flow."""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.events import ListPublisher
from billpilot.main import DESCRIPTION, create_app
from billpilot.synthetic.config import small_config
from billpilot.synthetic.generate import build_world

CUSTOMER = {"X-API-Key": "test-customer"}
CSR = {"X-API-Key": "test-csr"}
OPS = {"X-API-Key": "test-ops"}

BILLS = "/tmf-api/customerBillManagement/v4/customerBill"
RATES = "/tmf-api/customerBillManagement/v4/appliedCustomerBillingRate"
DISPUTES = "/tmf-api/customerBillManagement/v4/customerBillDispute"
ADJUSTMENTS = "/tmf-api/customerBillManagement/v4/billAdjustment"
USAGE = "/tmf-api/usageManagement/v4/usage"
OFFERINGS = "/tmf-api/productCatalogManagement/v4/productOffering"
PAYMENTS = "/tmf-api/paymentManagement/v4/payment"
PRODUCTS = "/tmf-api/productInventory/v4/product"
TICKETS = "/tmf-api/troubleTicket/v4/troubleTicket"
BUCKETS = "/tmf-api/prepayBalanceManagement/v4/bucket"


@pytest.fixture
def client(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as test_client:
        yield test_client


def _demo_account(session: Session) -> str:
    return str(
        session.execute(
            text(
                """
                SELECT accounts.id
                FROM accounts
                JOIN customers ON customers.id = accounts.customer_id
                WHERE customers.customer_number = 'CUST-000001'
                """
            )
        ).scalar_one()
    )


def _other_account(session: Session) -> str:
    document = build_world(small_config()).ground_truth
    return document["anomalies"][0]["account_id"]


def test_openapi_says_this_is_a_learning_mock(client: TestClient):
    document = client.get("/openapi.json").json()
    assert "not a certified" in document["info"]["description"]
    assert "not a certified" in DESCRIPTION
    paths = set(document["paths"])
    for path in (BILLS, RATES, DISPUTES, ADJUSTMENTS, USAGE, OFFERINGS, PAYMENTS, PRODUCTS, TICKETS, BUCKETS):
        assert path in paths
    assert f"{ADJUSTMENTS}/{{adjustment_id}}/approve" in paths


def test_health_is_public_and_echoes_a_request_id(client: TestClient):
    response = client.get("/health", headers={"X-Request-Id": "req-health"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-Id"] == "req-health"
    assert client.get("/").status_code == 200


def test_missing_and_unknown_keys_are_rejected(client: TestClient):
    assert client.get(BILLS).status_code == 401
    assert client.get(BILLS, headers={"X-API-Key": "nope"}).status_code == 401


def test_customer_sees_only_their_bills(client: TestClient, session: Session):
    own = client.get(BILLS, headers=CUSTOMER)
    assert own.status_code == 200
    body = own.json()
    assert body
    assert body[0]["@type"] == "CustomerBill"
    assert body[0]["taxIncludedAmount"]["unit"] == "INR"
    assert int(own.headers["X-Total-Count"]) >= len(body)
    other = _other_account(session)
    denied = client.get(BILLS, headers=CUSTOMER, params={"billingAccount.id": other})
    assert denied.status_code == 403
    missing = client.get(f"{BILLS}/{uuid.uuid4()}", headers=OPS)
    assert missing.status_code == 404


def test_pagination_and_filters(client: TestClient, session: Session):
    page = client.get(BILLS, headers=CUSTOMER, params={"limit": 1, "offset": 0})
    assert page.status_code == 200
    assert len(page.json()) == 1
    assert page.headers["X-Result-Count"] == "1"
    assert int(page.headers["X-Total-Count"]) >= 1
    bill_no = page.json()[0]["billNo"]
    filtered = client.get(BILLS, headers=CUSTOMER, params={"billNo": bill_no})
    assert [row["billNo"] for row in filtered.json()] == [bill_no]

    usage = client.get(USAGE, headers=CUSTOMER, params={"usageType": "data", "limit": 5})
    assert usage.status_code == 200
    assert usage.json()
    assert all(
        any(item["name"] == "eventType" and item["value"] == "data" for item in row["usageCharacteristic"])
        for row in usage.json()
    )

    offerings = client.get(OFFERINGS, headers=CUSTOMER)
    names = {row["name"] for row in offerings.json()}
    assert "Smart 199" in names
    rates = client.get(RATES, headers=CUSTOMER, params={"limit": 5})
    assert rates.status_code == 200 and rates.json()[0]["@type"] == "AppliedCustomerBillingRate"
    payments = client.get(PAYMENTS, headers=CUSTOMER)
    assert payments.status_code == 200
    products = client.get(PRODUCTS, headers=CUSTOMER)
    assert products.status_code == 200 and products.json()
    buckets = client.get(BUCKETS, headers=CUSTOMER, params={"limit": 5})
    assert buckets.status_code == 200
    assert "remainingValue" in buckets.json()[0]


def test_roles_cannot_cross_into_each_others_writes(client: TestClient, session: Session):
    account_id = _demo_account(session)
    dispute = {
        "billingAccount": {"id": account_id},
        "category": "billing",
        "description": "Please explain the latest bill.",
    }
    assert client.post(DISPUTES, headers=OPS, json=dispute).status_code == 403
    adjustment = {
        "billingAccount": {"id": account_id},
        "customerBill": {"id": str(uuid.uuid4())},
        "adjustmentType": "credit",
        "amount": {"unit": "INR", "value": "1.00"},
        "reason": "Should be refused before the bill is checked.",
    }
    assert client.post(ADJUSTMENTS, headers=CUSTOMER, json=adjustment).status_code == 403
    assert client.post(ADJUSTMENTS, headers=OPS, json=adjustment).status_code == 403
    assert client.get("/ops/auditLog", headers=CUSTOMER).status_code == 403
    assert client.get("/ops/auditLog", headers=CSR).status_code == 403
    other = _other_account(session)
    denied = client.post(
        TICKETS,
        headers=CSR,
        json={
            "billingAccount": {"id": other},
            "name": "Wrong account",
            "description": "This CSR is not assigned here.",
        },
    )
    assert denied.status_code == 403


def test_dispute_and_ticket_are_audited(client: TestClient, session: Session):
    account_id = _demo_account(session)
    publisher = ListPublisher()
    client.app.state.publisher = publisher
    created = client.post(
        DISPUTES,
        headers=CUSTOMER,
        json={
            "billingAccount": {"id": account_id},
            "category": "billing",
            "description": "I do not recognise a charge.",
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert publisher.events[0][0] == "treatment.actions"
    ticket = client.post(
        TICKETS,
        headers=CSR,
        json={
            "billingAccount": {"id": account_id},
            "name": "Bill question",
            "description": "Customer asked for a walkthrough of the latest bill.",
            "severity": "Minor",
        },
    )
    assert ticket.status_code == 201
    assert ticket.json()["status"] == "acknowledged"
    audit = client.get("/ops/auditLog", headers=OPS, params={"limit": 100})
    actions = {row["action"] for row in audit.json()}
    assert "dispute.create" in actions
    assert "ticket.create" in actions


def _unpaid_control() -> dict:
    document = build_world(small_config()).ground_truth
    return next(row for row in document["controls"] if row["type"] == "unpaid_treated")


def _invoice_money(session: Session, invoice_id: str) -> tuple[Decimal, Decimal]:
    session.expire_all()
    row = session.execute(
        text("SELECT total, amount_due FROM invoices WHERE id = :id"),
        {"id": invoice_id},
    ).one()
    return Decimal(row.total), Decimal(row.amount_due)


def test_adjustment_stays_pending_until_a_different_role_approves(client: TestClient, session: Session):
    control = _unpaid_control()
    account_id = control["account_id"]
    invoice_id = control["invoice_id"]
    before_total, before_due = _invoice_money(session, invoice_id)
    body = {
        "billingAccount": {"id": account_id},
        "customerBill": {"id": invoice_id},
        "adjustmentType": "credit",
        "amount": {"unit": "INR", "value": "10.00"},
        "reason": "Courtesy credit on a synthetic unpaid bill.",
    }
    publisher = ListPublisher()
    client.app.state.publisher = publisher
    proposed = client.post(ADJUSTMENTS, headers=CSR, json=body)
    assert proposed.status_code == 201
    adjustment = proposed.json()
    assert adjustment["status"] == "pending_approval"
    assert _invoice_money(session, invoice_id) == (before_total, before_due)

    approve_url = f"{ADJUSTMENTS}/{adjustment['id']}/approve"
    assert client.post(approve_url, headers=CSR, json={"decision": "approve"}).status_code == 403
    applied = client.post(approve_url, headers=OPS, json={"decision": "approve", "note": "Looks right."})
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    after_total, after_due = _invoice_money(session, invoice_id)
    assert after_total == before_total - Decimal("10.00")
    assert after_due == before_due - Decimal("10.00")
    assert publisher.events[-1][0] == "payment.events"
    assert publisher.events[-1][1]["kind"] == "adjustment_applied"
    assert client.post(approve_url, headers=OPS, json={"decision": "approve"}).status_code == 409

    rejected_body = dict(body)
    rejected_body["reason"] = "A second proposal that should be rejected."
    second = client.post(ADJUSTMENTS, headers=CSR, json=rejected_body)
    assert second.status_code == 201
    reject_url = f"{ADJUSTMENTS}/{second.json()['id']}/approve"
    rejected = client.post(reject_url, headers=OPS, json={"decision": "reject", "note": "Not this one."})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert _invoice_money(session, invoice_id) == (after_total, after_due)

    audit = client.get("/ops/auditLog", headers=OPS, params={"account.id": account_id, "limit": 100})
    actions = [row["action"] for row in audit.json()]
    assert "adjustment.propose" in actions
    assert "adjustment.apply" in actions
    assert "adjustment.reject" in actions


def test_customer_rate_limit_returns_429(seeded):
    del seeded
    settings = get_settings().model_copy(update={"rate_limit_customer_per_minute": 2})
    app = create_app(settings)
    with TestClient(app) as limited:
        assert limited.get("/health").status_code == 200
        assert limited.get(OFFERINGS, headers=CUSTOMER).status_code == 200
        assert limited.get(OFFERINGS, headers=CUSTOMER).status_code == 200
        blocked = limited.get(OFFERINGS, headers=CUSTOMER)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
