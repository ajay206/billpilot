"""A CSR proposal stays pending. The invoice total does not move."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.agent.fake import FakeChatModel
from billpilot.agent.loop import run_agent
from billpilot.agent.model import Completion, ScriptedChatModel, ToolCall
from billpilot.agent.tools import BssClient, ThreadedASGITransport
from billpilot.config import get_settings
from billpilot.main import create_app
from billpilot.synthetic.config import small_config
from billpilot.synthetic.generate import build_world


def _double_charge() -> dict:
    document = build_world(small_config()).ground_truth
    return next(row for row in document["anomalies"] if row["type"] == "double_charge")


def test_csr_proposes_a_credit_and_the_bill_is_unchanged(seeded, session: Session):
    anomaly = _double_charge()
    before = session.execute(
        text("SELECT total FROM invoices WHERE id = :id"),
        {"id": anomaly["invoice_id"]},
    ).scalar_one()
    assignee = session.execute(
        text("SELECT assigned_csr FROM accounts WHERE id = :id"),
        {"id": anomaly["account_id"]},
    ).scalar_one()
    settings = get_settings().model_copy(update={"csr_code": assignee, "llm_backend": "fake"})
    app = create_app(settings)
    bss = BssClient("http://billpilot.internal", settings.api_key_csr, transport=ThreadedASGITransport(app))
    try:
        result = run_agent(
            message="Investigate a billing dispute and propose a credit if the evidence supports one.",
            persona="csr",
            actor_id=f"csr:{assignee}",
            bss=bss,
            model=FakeChatModel(),
            session=session,
            request_id="propose-test",
            settings=settings,
            account_id=anomaly["account_id"],
            customer_number=None,
        )
    finally:
        bss.close()
    after = session.execute(
        text("SELECT total FROM invoices WHERE id = :id"),
        {"id": anomaly["invoice_id"]},
    ).scalar_one()
    assert before == after
    credits = [action for action in result.proposed_actions if action["type"] == "credit"]
    assert credits
    assert credits[0]["status"] == "pending_approval"
    assert credits[0]["applied"] is False
    assert all("approve" not in call["name"] for call in result.tool_calls)
    stored = session.execute(
        text("SELECT status FROM adjustments WHERE id = :id"),
        {"id": credits[0]["id"]},
    ).scalar_one()
    assert stored == "pending_approval"
    linked = session.execute(
        text(
            """
            SELECT audit_log.action
            FROM agent_runs
            JOIN audit_log ON audit_log.id = agent_runs.audit_log_id
            WHERE agent_runs.id = :id
            """
        ),
        {"id": result.run_id},
    ).scalar_one()
    assert linked == "agent.chat"


def test_a_hallucinated_approve_tool_is_rejected(seeded, session: Session):
    anomaly = _double_charge()
    before = session.execute(
        text("SELECT total FROM invoices WHERE id = :id"), {"id": anomaly["invoice_id"]}
    ).scalar_one()
    settings = get_settings()
    app = create_app(settings)
    model = ScriptedChatModel(
        [
            Completion(
                content="",
                tool_calls=[ToolCall(id="call-approve", name="approve_adjustment", arguments={"id": "x"})],
                prompt_tokens=3,
                completion_tokens=1,
                model="scripted",
            ),
            Completion(content="I approved it.", prompt_tokens=3, completion_tokens=2, model="scripted"),
        ]
    )
    bss = BssClient("http://billpilot.internal", settings.api_key_ops, transport=ThreadedASGITransport(app))
    try:
        result = run_agent(
            message="Explain the latest bill line by line and compare it with the previous month and the tariff.",
            persona="ops",
            actor_id="ops",
            bss=bss,
            model=model,
            session=session,
            request_id="approve-test",
            settings=settings,
            account_id=anomaly["account_id"],
        )
    finally:
        bss.close()
    after = session.execute(
        text("SELECT total FROM invoices WHERE id = :id"), {"id": anomaly["invoice_id"]}
    ).scalar_one()
    assert before == after
    assert result.tool_calls[0]["name"] == "approve_adjustment"
    assert result.tool_calls[0]["ok"] is False
    assert result.proposed_actions == []


def test_an_amount_the_tools_did_not_return_is_not_shown(seeded, session: Session):
    settings = get_settings()
    app = create_app(settings)
    model = ScriptedChatModel(
        [
            Completion(
                content="The credit is 99999.00 INR and it was a guess.",
                prompt_tokens=4,
                completion_tokens=4,
                model="scripted",
            )
        ]
    )
    bss = BssClient("http://billpilot.internal", settings.api_key_customer, transport=ThreadedASGITransport(app))
    try:
        result = run_agent(
            message="Explain the latest bill line by line and compare it with the previous month and the tariff.",
            persona="customer",
            actor_id="customer:CUST-000001",
            bss=bss,
            model=model,
            session=session,
            request_id="ground-test",
            settings=settings,
            customer_number="CUST-000001",
        )
    finally:
        bss.close()
    assert "99999.00" not in result.answer
    assert result.grounded is False
