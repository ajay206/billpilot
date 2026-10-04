"""One call opens a customer, provisions the line, and previews the first bill."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.events import ListPublisher
from billpilot.main import create_app
from tests.test_migration import purge_phase5

OPS = {"X-API-Key": "test-ops"}
CSR = {"X-API-Key": "test-csr"}
CUSTOMER = {"X-API-Key": "test-customer"}


def _body(**overrides):
    payload = {
        "givenName": "Asha",
        "familyName": "Iyer",
        "email": "asha.onboard@example.com",
        "phone": "+919876543210",
        "city": "Pune",
        "state": "Maharashtra",
        "msisdn": "9876543210",
        "planCode": "PLUS-399",
        "billingCycleDay": 1,
        "optedInVas": ["CALLER-TUNE"],
    }
    payload.update(overrides)
    return payload


def test_onboarding_provisions_entitlements_treatment_credit_and_a_preview(seeded, session: Session):
    del seeded
    purge_phase5(session)
    app = create_app(get_settings())
    app.state.publisher = ListPublisher()
    with TestClient(app) as client:
        created = client.post("/onboarding", headers=CSR, json=_body())
        assert created.status_code == 201, created.text
        same = client.post(
            "/tmf-api/customerManagement/v4/onboarding",
            headers=OPS,
            json=_body(email="second.onboard@example.com", msisdn="9876543211", optedInVas=[]),
        )
        assert same.status_code == 201, same.text
    body = created.json()
    assert body["@type"] == "CustomerOnboarding"
    assert body["customerNumber"].startswith("ONB-")
    assert body["planCode"] == "PLUS-399"
    assert body["treatmentStage"] == "none"
    assert body["treatmentStatus"] == "active"
    assert body["creditClass"] == "new"
    assert body["creditLimit"] == "798.00"
    assert body["vas"] == ["CALLER-TUNE"]
    assert [row["feature"] for row in body["entitlements"]] == ["voice", "data", "sms"]
    assert all(row["status"] == "active" for row in body["entitlements"])
    preview = body["firstBillPreview"]
    assert preview["posted"] is False
    assert preview["subtotal"] == "429.00"
    assert preview["tax"] == "77.22"
    assert preview["total"] == "506.22"
    assert "Welcome, Asha" in body["welcomeMessage"]
    assert "not posted" in body["welcomeMessage"]
    bare = same.json()
    assert bare["vas"] == []
    assert bare["firstBillPreview"]["total"] == "470.82"
    topics = [topic for topic, _payload in app.state.publisher.events]
    assert "entitlement.changes" in topics
    assert "treatment.actions" in topics
    invoices = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM invoices i
            JOIN accounts a ON a.id = i.account_id
            JOIN customers c ON c.id = a.customer_id
            WHERE c.customer_number LIKE 'ONB-%'
            """
        )
    )
    assert invoices == 0
    audit = session.scalar(
        text("SELECT COUNT(*) FROM audit_log WHERE action = 'onboarding.create' AND resource_id = :id"),
        {"id": body["id"]},
    )
    assert audit == 1
    profiles = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM credit_profiles p
            JOIN accounts a ON a.id = p.account_id
            JOIN customers c ON c.id = a.customer_id
            WHERE c.customer_number LIKE 'ONB-%' AND p.credit_class = 'new'
            """
        )
    )
    assert profiles == 2
    purge_phase5(session)


def test_onboarding_rejects_bad_input_and_the_customer_role(seeded, session: Session):
    del seeded
    purge_phase5(session)
    app = create_app(get_settings())
    with TestClient(app) as client:
        denied = client.post("/onboarding", headers=CUSTOMER, json=_body())
        assert denied.status_code == 403
        bad_msisdn = client.post("/onboarding", headers=OPS, json=_body(msisdn="12AB"))
        assert bad_msisdn.status_code == 422
        assert "MSISDN" in bad_msisdn.json()["message"]
        unknown = client.post("/onboarding", headers=OPS, json=_body(planCode="LEG-GONE"))
        assert unknown.status_code == 422
        vas = client.post("/onboarding", headers=OPS, json=_body(optedInVas=["NOT-A-PACK"]))
        assert vas.status_code == 422
        first = client.post("/onboarding", headers=CSR, json=_body())
        assert first.status_code == 201
        duplicate = client.post("/onboarding", headers=CSR, json=_body())
        assert duplicate.status_code == 409
    assert session.scalar(text("SELECT COUNT(*) FROM customers WHERE email = 'asha.onboard@example.com'")) == 1
    purge_phase5(session)
