"""Outbox publisher and the failure consumer.

Postgres mode is the queue: consumers read `pending` rows. Redpanda mode writes
the same row, then relays it onto the broker. The apply function is the same
either way. A poison payload is the only synthetic event that is meant to fail
until it lands on the dead-letter table.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from billpilot.config import Settings
from billpilot.db import get_session_factory
from billpilot.models import BillRun, ConsumerCursor, DeadLetter, Incident, OutboxEvent
from billpilot.ops.topics import CONSUMER_NAME, TOPICS

logger = logging.getLogger("billpilot.ops.pipeline")


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid(value) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _when(payload: dict, row: OutboxEvent) -> datetime:
    raw = payload.get("occurredAt")
    if not raw:
        return row.occurred_at
    parsed = datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def envelope(row: OutboxEvent) -> dict:
    return {
        "eventId": str(row.id),
        "topic": row.topic,
        "eventType": row.event_type,
        "occurredAt": row.occurred_at.isoformat(),
        "payload": row.payload,
    }


class OutboxPublisher:
    """Writes the outbox in the caller's transaction. Redpanda relay runs after commit."""

    def __init__(self, settings: Settings, transport=None) -> None:
        self.settings = settings
        self.transport = transport

    def publish(self, topic: str, payload: dict, *, session: Session | None = None) -> str:
        event_id = uuid.uuid4()
        occurred = _parse_occurred(payload)
        account_id = _uuid(payload.get("accountId"))
        row = OutboxEvent(
            id=event_id,
            topic=topic,
            event_type=str(payload.get("eventType") or topic),
            payload=payload,
            account_id=account_id,
            occurred_at=occurred,
            status="pending",
            retry_count=0,
            last_error=None,
            idempotency_key=None if payload.get("idempotencyKey") is None else str(payload.get("idempotencyKey")),
            created_at=_now(),
            published_at=None,
        )
        own = session is None
        if own:
            session = get_session_factory()()
        session.add(row)
        if own:
            session.commit()
            if self._relays:
                self.relay([event_id])
            session.close()
        elif self._relays:
            self._arm(session, event_id)
        return str(event_id)

    @property
    def _relays(self) -> bool:
        return self.settings.event_backend == "redpanda" and self.transport is not None

    def _arm(self, session: Session, event_id: uuid.UUID) -> None:
        pending: list[uuid.UUID] = session.info.setdefault("billpilot_relay_ids", [])
        pending.append(event_id)
        if session.info.get("billpilot_relay_armed"):
            return
        session.info["billpilot_relay_armed"] = True
        publisher = self

        def _after_commit(_session) -> None:
            publisher.relay(list(pending))

        event.listen(session, "after_commit", _after_commit, once=True)

    def relay(self, ids: list[uuid.UUID]) -> int:
        if not ids or self.transport is None:
            return 0
        sent = 0
        with get_session_factory()() as session:
            rows = session.scalars(select(OutboxEvent).where(OutboxEvent.id.in_(ids))).all()
            for row in rows:
                if row.status != "pending":
                    continue
                self.transport.produce(row.topic, str(row.id), envelope(row))
                result = session.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == row.id, OutboxEvent.status == "pending")
                    .values(status="queued")
                )
                sent += result.rowcount or 0
            session.commit()
        return sent


def _parse_occurred(payload: dict) -> datetime:
    raw = payload.get("occurredAt")
    if not raw:
        return _now()
    parsed = datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def build_publisher(settings: Settings, transport=None) -> OutboxPublisher:
    if transport is None and settings.event_backend == "redpanda":
        from billpilot.ops.bus import RedpandaBroker

        transport = RedpandaBroker(settings.redpanda_bootstrap)
    return OutboxPublisher(settings, transport)


def apply_event(session: Session, row: OutboxEvent) -> None:
    """Turn one event into bill-run rows and incidents. Idempotent on the event id."""
    payload = row.payload or {}
    if row.event_type == "system.error.poison" and not payload.get("replayOf"):
        raise RuntimeError("synthetic poison event")
    kind = row.event_type
    if kind == "bill.run.started":
        _bill_started(session, row)
    elif kind == "bill.run.finished":
        _bill_finished(session, row)
    elif kind == "bill.run.failed":
        _bill_failed(session, row)
    elif kind == "payment.failed":
        _open_incident(session, row, "failed_payment", "high", "Payment failed")
    elif kind == "payment.autopay_failed":
        _open_incident(session, row, "failed_autopay", "high", "Autopay failed")
    elif kind == "provisioning.mismatch":
        _open_incident(session, row, "provisioning_mismatch", "high", "Provisioning mismatch")
    elif kind == "entitlement.mismatch":
        _open_incident(session, row, "entitlement_mismatch", "medium", "Entitlement mismatch")


def _run_key(row: OutboxEvent) -> str:
    return str((row.payload or {}).get("runKey") or row.id)


def _bill_started(session: Session, row: OutboxEvent) -> None:
    key = _run_key(row)
    existing = session.scalar(select(BillRun).where(BillRun.run_key == key))
    if existing is not None:
        return
    session.add(
        BillRun(
            id=uuid.uuid4(),
            run_key=key,
            account_id=row.account_id,
            status="started",
            started_at=_when(row.payload or {}, row),
            finished_at=None,
            error=None,
            source_event_id=row.id,
        )
    )


def _bill_finished(session: Session, row: OutboxEvent) -> None:
    run = session.scalar(select(BillRun).where(BillRun.run_key == _run_key(row)))
    if run is None or run.status in {"finished", "failed"}:
        return
    run.status = "finished"
    run.finished_at = _when(row.payload or {}, row)


def _bill_failed(session: Session, row: OutboxEvent) -> None:
    run = session.scalar(select(BillRun).where(BillRun.run_key == _run_key(row)))
    if run is None:
        run = BillRun(
            id=uuid.uuid4(),
            run_key=_run_key(row),
            account_id=row.account_id,
            status="failed",
            started_at=_when(row.payload or {}, row),
            finished_at=_when(row.payload or {}, row),
            error=str((row.payload or {}).get("error") or "bill run failed"),
            source_event_id=row.id,
        )
        session.add(run)
    elif run.status != "failed":
        run.status = "failed"
        run.finished_at = _when(row.payload or {}, row)
        run.error = str((row.payload or {}).get("error") or "bill run failed")
    _open_incident(session, row, "failed_bill_run", "high", "Bill run failed")


def _open_incident(session: Session, row: OutboxEvent, incident_type: str, severity: str, title: str) -> None:
    existing = session.scalar(select(Incident).where(Incident.source_event_id == row.id))
    if existing is not None:
        return
    payload = row.payload or {}
    detail = str(payload.get("detail") or payload.get("error") or title)
    session.add(
        Incident(
            id=uuid.uuid4(),
            incident_type=incident_type,
            severity=severity,
            status="open",
            title=title[:200],
            description=detail[:2000],
            detected_at=_when(payload, row),
            related_entity_type="account" if row.account_id else None,
            related_entity_id=row.account_id,
            account_id=row.account_id,
            source_event_id=row.id,
            evidence={"topic": row.topic, "eventType": row.event_type, "eventId": str(row.id)},
        )
    )


def _dead_letter(session: Session, row: OutboxEvent) -> None:
    row.status = "dead"
    already = session.scalar(select(DeadLetter).where(DeadLetter.outbox_event_id == row.id))
    if already is None:
        session.add(
            DeadLetter(
                id=uuid.uuid4(),
                outbox_event_id=row.id,
                topic=row.topic,
                event_type=row.event_type,
                payload=row.payload,
                error=row.last_error or "failed",
                retry_count=row.retry_count,
                status="open",
                replay_event_id=None,
                created_at=_now(),
                replayed_at=None,
            )
        )
    _open_incident(session, row, "dead_letter", "critical", "Dead-letter event")


def _handle(session: Session, row: OutboxEvent, settings: Settings) -> None:
    """Apply one event, retrying in this pass until it publishes or is dead-lettered."""
    while row.status not in {"published", "dead"}:
        try:
            with session.begin_nested():
                apply_event(session, row)
                row.status = "published"
                row.published_at = _now()
        except Exception as exc:
            row.retry_count += 1
            row.last_error = str(exc)[:500]
            if row.retry_count >= settings.event_max_retries:
                _dead_letter(session, row)
    _touch_cursor(session, row.topic)


def _touch_cursor(session: Session, topic: str) -> None:
    cursor = session.get(ConsumerCursor, (CONSUMER_NAME, topic))
    if cursor is None:
        session.add(
            ConsumerCursor(
                consumer_name=CONSUMER_NAME,
                topic=topic,
                committed_count=1,
                updated_at=_now(),
            )
        )
        return
    cursor.committed_count += 1
    cursor.updated_at = _now()


def consume_outbox(session: Session, settings: Settings, limit: int = 50) -> int:
    rows = session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.status == "pending")
        .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        _handle(session, row, settings)
    session.commit()
    return len(rows)


def consume_broker(session: Session, settings: Settings, transport, limit: int = 50) -> int:
    messages = transport.poll(TOPICS, CONSUMER_NAME, limit)
    handled = 0
    for message in messages:
        event_id = _uuid((message.value or {}).get("eventId"))
        row = None if event_id is None else session.get(OutboxEvent, event_id)
        if row is None or row.status == "published":
            transport.commit(CONSUMER_NAME, message.topic, message.offset)
            continue
        _handle(session, row, settings)
        session.commit()
        transport.commit(CONSUMER_NAME, message.topic, message.offset)
        handled += 1
    return handled


def drain(session: Session, settings: Settings, transport=None, passes: int = 6) -> int:
    """Apply until the queue is quiet. Poison events need one pass per retry."""
    total = 0
    for _ in range(passes):
        if settings.event_backend == "redpanda" and transport is not None:
            count = consume_broker(session, settings, transport)
        else:
            count = consume_outbox(session, settings)
        total += count
        swept = sweep_stuck(session, settings)
        session.commit()
        if count == 0 and swept == 0:
            break
    return total


def sweep_stuck(session: Session, settings: Settings) -> int:
    cutoff = _now() - timedelta(seconds=settings.stuck_bill_run_seconds)
    runs = session.scalars(select(BillRun).where(BillRun.status == "started", BillRun.started_at < cutoff)).all()
    opened = 0
    for run in runs:
        run.status = "stuck"
        existing = session.scalar(select(Incident).where(Incident.source_event_id == run.id))
        if existing is not None:
            continue
        session.add(
            Incident(
                id=uuid.uuid4(),
                incident_type="stuck_bill_run",
                severity="high",
                status="open",
                title="Bill run stuck",
                description="The bill run started and never finished or failed.",
                detected_at=_now(),
                related_entity_type="bill_run",
                related_entity_id=run.id,
                account_id=run.account_id,
                source_event_id=run.id,
                evidence={"runKey": run.run_key, "startedAt": run.started_at.isoformat()},
            )
        )
        opened += 1
    return opened


def replay_dead_letter(session: Session, dead_letter_id: uuid.UUID) -> tuple[OutboxEvent, bool]:
    """Queue the payload again. A second call returns the same new event."""
    letter = session.get(DeadLetter, dead_letter_id, with_for_update=True)
    if letter is None:
        raise KeyError(dead_letter_id)
    if letter.replay_event_id is not None:
        existing = session.get(OutboxEvent, letter.replay_event_id)
        if existing is None:
            raise KeyError(letter.replay_event_id)
        return existing, True
    payload = dict(letter.payload or {})
    payload["replayOf"] = str(letter.outbox_event_id)
    payload["eventType"] = letter.event_type
    payload["idempotencyKey"] = f"replay:{letter.id}"
    new_id = uuid.uuid4()
    row = OutboxEvent(
        id=new_id,
        topic=letter.topic,
        event_type=letter.event_type,
        payload=payload,
        account_id=_uuid(payload.get("accountId")),
        occurred_at=_now(),
        status="pending",
        retry_count=0,
        last_error=None,
        idempotency_key=f"replay:{letter.id}",
        created_at=_now(),
        published_at=None,
    )
    session.add(row)
    letter.status = "replayed"
    letter.replay_event_id = new_id
    letter.replayed_at = _now()
    return row, False


def lag_snapshot(session: Session, settings: Settings, transport=None) -> dict:
    from sqlalchemy import text

    # Topic names are a fixed tuple in code, not request input.
    values = ", ".join(f"('{topic}')" for topic in TOPICS)
    rows = session.execute(
        text(
            f"""
            SELECT topic.name AS topic,
                   COALESCE(COUNT(e.id) FILTER (WHERE e.status IN ('pending', 'processing')), 0) AS pending,
                   COALESCE(COUNT(e.id) FILTER (WHERE e.status = 'queued'), 0) AS queued,
                   COALESCE(COUNT(e.id) FILTER (WHERE e.status = 'dead'), 0) AS dead,
                   COALESCE(COUNT(e.id) FILTER (WHERE e.status = 'published'), 0) AS published
            FROM (VALUES {values}) AS topic(name)
            LEFT JOIN outbox_events e ON e.topic = topic.name
            GROUP BY topic.name
            ORDER BY topic.name
            """
        )
    ).mappings()
    topics = []
    for row in rows:
        pending = int(row["pending"])
        queued = int(row["queued"])
        lag = queued if settings.event_backend == "redpanda" else pending
        topics.append(
            {
                "topic": row["topic"],
                "lag": lag,
                "pending": pending,
                "queued": queued,
                "dead": int(row["dead"]),
                "published": int(row["published"]),
            }
        )
    broker = None
    if settings.event_backend == "redpanda" and transport is not None:
        try:
            broker = transport.lag(TOPICS, CONSUMER_NAME)
        except Exception:
            logger.exception("Broker lag was not readable.")
            broker = None
    cursors = session.scalars(select(ConsumerCursor).where(ConsumerCursor.consumer_name == CONSUMER_NAME)).all()
    return {
        "backend": settings.event_backend,
        "topics": topics,
        "brokerLag": broker,
        "cursors": [
            {"topic": cursor.topic, "committed": cursor.committed_count, "updatedAt": cursor.updated_at.isoformat()}
            for cursor in cursors
        ],
    }
