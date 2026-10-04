"""Outbox publisher, failure consumer, dead-letter replay, and role checks."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.db import get_engine
from billpilot.main import create_app
from billpilot.models import AuditLog, DeadLetter, Incident, OutboxEvent
from billpilot.ops.bus import MemoryBroker
from billpilot.ops.pipeline import OutboxPublisher, consume_broker, consume_outbox, drain, lag_snapshot
from billpilot.ops.simulate import simulate


def test_postgres_consumer_opens_a_payment_incident(session: Session):
    settings = get_settings()
    publisher = OutboxPublisher(settings)
    simulate(session, publisher, settings, ["payment_failed"])
    incident = session.scalar(select(Incident).where(Incident.incident_type == "failed_payment"))
    assert incident is not None
    assert incident.account_id is not None
    assert incident.source_event_id is not None


def test_poison_is_dead_lettered_in_one_consume_pass(session: Session):
    settings = get_settings()
    publisher = OutboxPublisher(settings)
    event_id = publisher.publish(
        "system.errors",
        {"eventType": "system.error.poison", "detail": "Synthetic poison event."},
        session=session,
    )
    session.commit()
    assert consume_outbox(session, settings) == 1
    row = session.get(OutboxEvent, event_id)
    assert row is not None
    assert row.status == "dead"
    assert row.retry_count == settings.event_max_retries
    letter = session.scalar(select(DeadLetter).where(DeadLetter.outbox_event_id == row.id))
    assert letter is not None
    assert letter.retry_count == settings.event_max_retries
    incident = session.scalar(select(Incident).where(Incident.source_event_id == row.id))
    assert incident is not None
    assert incident.incident_type == "dead_letter"


def test_stuck_bill_run_opens_an_incident(session: Session):
    settings = get_settings()
    publisher = OutboxPublisher(settings)
    simulate(session, publisher, settings, ["bill_run_stuck"])
    incident = session.scalar(select(Incident).where(Incident.title == "Bill run stuck"))
    assert incident is not None
    assert incident.incident_type == "stuck_bill_run"
    assert incident.evidence.get("runKey")


def test_memory_broker_lag_drops_after_consume(session: Session):
    settings = get_settings().model_copy(update={"event_backend": "redpanda"})
    broker = MemoryBroker()
    publisher = OutboxPublisher(settings, broker)
    event_id = publisher.publish(
        "payment.events",
        {"eventType": "payment.failed", "detail": "Gateway declined the charge."},
        session=session,
    )
    session.commit()
    before = lag_snapshot(session, settings, broker)
    payment = next(item for item in before["topics"] if item["topic"] == "payment.events")
    assert payment["queued"] >= 1
    assert payment["lag"] >= 1
    broker_lag = next(item for item in before["brokerLag"] if item["topic"] == "payment.events")
    assert broker_lag["lag"] >= 1
    assert consume_broker(session, settings, broker) == 1
    after = lag_snapshot(session, settings, broker)
    payment = next(item for item in after["topics"] if item["topic"] == "payment.events")
    assert payment["lag"] == 0
    published = session.get(OutboxEvent, event_id)
    assert published is not None
    assert published.status == "published"


def test_replay_is_idempotent_and_audited(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as client:
        ops = {"X-API-Key": "test-ops"}
        simulated = client.post("/ops/faults/simulate", headers=ops, json={"scenarios": ["poison"]})
        assert simulated.status_code == 200
        snapshot = client.get("/ops/failures", headers=ops)
        assert snapshot.status_code == 200
        letters = [row for row in snapshot.json()["deadLetters"] if row["eventType"] == "system.error.poison"]
        assert letters
        letter_id = letters[0]["id"]
        first = client.post(f"/ops/deadLetters/{letter_id}/replay", headers=ops)
        second = client.post(f"/ops/deadLetters/{letter_id}/replay", headers=ops)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert first.json()["replayEventId"] == second.json()["replayEventId"]
        again = client.get("/ops/failures", headers=ops).json()
        replayed = next(row for row in again["deadLetters"] if row["id"] == letter_id)
        assert replayed["status"] == "replayed"
    with Session(get_engine()) as session:
        audits = session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "dead_letter.replay")
        )
        copies = session.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.idempotency_key == f"replay:{letter_id}")
        )
    assert audits == 1
    assert copies == 1


def test_replayed_poison_publishes(session: Session):
    settings = get_settings()
    publisher = OutboxPublisher(settings)
    event_id = publisher.publish(
        "system.errors",
        {"eventType": "system.error.poison", "detail": "Synthetic poison event."},
        session=session,
    )
    session.commit()
    consume_outbox(session, settings)
    letter = session.scalar(select(DeadLetter).where(DeadLetter.outbox_event_id == event_id))
    assert letter is not None
    from billpilot.ops.pipeline import replay_dead_letter

    replayed, duplicate = replay_dead_letter(session, letter.id)
    session.commit()
    assert duplicate is False
    drain(session, settings)
    stored = session.get(OutboxEvent, replayed.id)
    assert stored is not None
    assert stored.status == "published"


def test_ops_routes_reject_other_roles(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as client:
        customer = {"X-API-Key": "test-customer"}
        csr = {"X-API-Key": "test-csr"}
        ops = {"X-API-Key": "test-ops"}
        assert client.get("/ops/failures", headers=customer).status_code == 403
        assert client.get("/ops/failures", headers=csr).status_code == 403
        assert client.post("/ops/faults/simulate", headers=csr, json={}).status_code == 403
        assert client.get("/ops/reports", headers=customer).status_code == 403
        assert client.post("/ops/assurance/run", headers=csr).status_code == 403
        assert client.get("/ops/failures", headers=ops).status_code == 200
        assert client.get("/ops/incidents", headers=csr).status_code == 200


def test_session_customer_and_csr_are_forbidden_on_ops_routes(seeded):
    """Cookie sessions send CSRF. A 403 here is the role, not a missing token."""
    del seeded
    app = create_app(get_settings())
    writes = (
        ("post", "/ops/faults/simulate"),
        ("post", "/ops/reports/generate"),
        ("post", "/ops/assurance/run"),
        ("post", "/ops/findings/00000000-0000-0000-0000-000000000001/case"),
        ("post", "/ops/findings/00000000-0000-0000-0000-000000000001/adjustment"),
        ("post", "/ops/deadLetters/00000000-0000-0000-0000-000000000001/replay"),
    )
    reads = ("/ops/failures", "/ops/reports", "/ops/findings")
    with TestClient(app) as client:
        for username in ("priya.sharma", "ananya.rao"):
            signed = client.post("/auth/login", json={"username": username, "password": _demo_password(username)})
            assert signed.status_code == 200, signed.text
            csrf = {"X-CSRF-Token": signed.json()["csrfToken"]}
            for path in reads:
                response = client.get(path)
                assert response.status_code == 403, (username, path, response.text)
                assert "cannot perform" in response.json()["message"]
            for method, path in writes:
                response = client.request(method, path, headers=csrf, json={})
                assert response.status_code == 403, (username, path, response.text)
                assert "cannot perform" in response.json()["message"]
            client.post("/auth/logout", headers=csrf)
        meera = client.post(
            "/auth/login",
            json={"username": "meera.kapoor", "password": _demo_password("meera.kapoor")},
        )
        assert meera.status_code == 200, meera.text
        assert client.get("/ops/failures").status_code == 200


def _demo_password(username: str) -> str:
    from billpilot.auth.demo import DEMO_USERS

    return next(item.password for item in DEMO_USERS if item.username == username)
