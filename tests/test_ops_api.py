"""Assurance actions stay proposals, and the CSR troubleshoot route cites a runbook."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from billpilot.config import get_settings
from billpilot.db import get_engine
from billpilot.main import create_app


def test_ops_can_open_a_case_and_cannot_approve_its_own_credit(seeded):
    del seeded
    app = create_app(get_settings())
    ops = {"X-API-Key": "test-ops"}
    with TestClient(app) as client:
        ran = client.post("/ops/assurance/run", headers=ops)
        assert ran.status_code == 200
        rows = ran.json()["rows"]
        assert rows
        billed = next(row for row in rows if row["evidence"].get("invoice_id"))
        invoice = next(field for field in billed["evidenceFields"] if field["label"] == "Invoice")
        assert invoice["value"] != billed["evidence"]["invoice_id"]
        assert billed["holderName"]
        assert billed["customerNumber"].startswith("CUST-")
        credited = next(row for row in rows if row["evidence"].get("pre_tax_amount"))
        opened = client.post(f"/ops/findings/{credited['id']}/case", headers=ops)
        assert opened.status_code == 200
        again = client.post(f"/ops/findings/{credited['id']}/case", headers=ops)
        assert again.status_code == 200
        assert again.json()["duplicate"] is True
        assert again.json()["ticketId"] == opened.json()["ticketId"]
        proposed = client.post(f"/ops/findings/{credited['id']}/adjustment", headers=ops)
        assert proposed.status_code == 200
        assert proposed.json()["status"] == "pending_approval"
        decision = client.post(
            f"/tmf-api/customerBillManagement/v4/billAdjustment/{proposed.json()['adjustmentId']}/approve",
            headers=ops,
            json={"decision": "approve"},
        )
        assert decision.status_code == 403


def test_csr_troubleshoot_returns_numbered_steps(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as client:
        with get_engine().connect() as connection:
            account_id = connection.execute(
                text("SELECT id FROM accounts WHERE assigned_csr = :csr ORDER BY account_number LIMIT 1"),
                {"csr": get_settings().csr_code},
            ).scalar()
        message = "Troubleshooting: a payment failed with token PAYMENT_DECLINED. Follow the failed payment runbook."
        response = client.post(
            "/agent/troubleshoot",
            headers={"X-API-Key": "test-csr"},
            json={"accountId": str(account_id), "message": message},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["refusal"] is False
        assert "1." in body["answer"]
        assert "csr-runbooks.md" in body["answer"]
        assert "Failed payment" in body["answer"]
        assert "relatedIncidents" in body
        names = [call["name"] for call in body["toolCalls"]]
        assert "search_knowledge" in names
        assert "list_incidents" in names
        assert "propose_adjustment" not in names
        knowledge = next(call for call in body["toolCalls"] if call["name"] == "search_knowledge")
        assert "csr-runbooks.md" in knowledge["summary"]
        assert "Failed payment" in knowledge["summary"]
        assert not knowledge["summary"].lstrip().startswith("{")
        for call in body["toolCalls"]:
            assert "summary" in call
            assert not str(call["summary"]).lstrip().startswith("[")


def test_session_csr_troubleshoot_stays_on_assigned_accounts(seeded):
    del seeded
    app = create_app(get_settings())
    message = "Troubleshooting: a payment failed with token PAYMENT_DECLINED. Follow the failed payment runbook."
    with TestClient(app) as client:
        with get_engine().connect() as connection:
            assigned = connection.execute(
                text("SELECT id FROM accounts WHERE assigned_csr = 'CSR-A' ORDER BY account_number LIMIT 1")
            ).scalar_one()
            other = connection.execute(
                text("SELECT id FROM accounts WHERE assigned_csr = 'CSR-B' ORDER BY account_number LIMIT 1")
            ).scalar_one()
        signed = client.post("/auth/login", json={"username": "ananya.rao", "password": "demo-ananya"})
        assert signed.status_code == 200, signed.text
        csrf = {"X-CSRF-Token": signed.json()["csrfToken"]}
        denied = client.post(
            "/agent/troubleshoot",
            headers=csrf,
            json={"accountId": str(other), "message": message},
        )
        assert denied.status_code == 403
        allowed = client.post(
            "/agent/troubleshoot",
            headers=csrf,
            json={"accountId": str(assigned), "message": message},
        )
        assert allowed.status_code == 200, allowed.text
        assert "1." in allowed.json()["answer"]
