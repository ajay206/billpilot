"""Synthetic failures for a demo. Nothing here is a real subscriber event."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from billpilot.config import Settings
from billpilot.models import Account
from billpilot.ops.pipeline import OutboxPublisher, drain

SCENARIOS: tuple[str, ...] = (
    "usage_rated",
    "bill_run_failed",
    "bill_run_stuck",
    "payment_posted",
    "payment_failed",
    "autopay_failed",
    "adjustment_proposed",
    "treatment_step",
    "entitlement_changed",
    "provisioning_mismatch",
    "entitlement_mismatch",
    "poison",
)


def simulate(
    session: Session,
    publisher: OutboxPublisher,
    settings: Settings,
    scenarios: list[str] | None = None,
) -> list[str]:
    """Publish the requested failures and run the consumer so incidents show up."""
    chosen = list(scenarios or SCENARIOS)
    unknown = [name for name in chosen if name not in SCENARIOS]
    if unknown:
        raise ValueError(f"Unknown scenario: {', '.join(unknown)}")
    account_id = session.scalar(select(Account.id).order_by(Account.account_number).limit(1))
    account = None if account_id is None else str(account_id)
    past = datetime.now(UTC) - timedelta(seconds=settings.stuck_bill_run_seconds + 120)
    event_ids: list[str] = []
    for name in chosen:
        event_ids.extend(_emit(publisher, session, name, account, past))
    session.commit()
    drain(session, settings, publisher.transport)
    return event_ids


def _emit(publisher: OutboxPublisher, session: Session, name: str, account: str | None, past: datetime) -> list[str]:
    base = {"accountId": account} if account else {}
    if name == "usage_rated":
        return [
            _one(
                publisher, session, "usage.rated", {**base, "eventType": "usage.rated", "detail": "Rated voice usage."}
            )
        ]
    if name == "payment_posted":
        return [
            _one(
                publisher,
                session,
                "payment.events",
                {**base, "eventType": "payment.posted", "detail": "Payment posted."},
            )
        ]
    if name == "payment_failed":
        return [
            _one(
                publisher,
                session,
                "payment.events",
                {**base, "eventType": "payment.failed", "detail": "The payment gateway declined the charge."},
            )
        ]
    if name == "autopay_failed":
        return [
            _one(
                publisher,
                session,
                "payment.events",
                {
                    **base,
                    "eventType": "payment.autopay_failed",
                    "detail": "Autopay was declined. No payment row was posted.",
                },
            )
        ]
    if name == "adjustment_proposed":
        return [
            _one(
                publisher,
                session,
                "payment.events",
                {**base, "eventType": "adjustment.proposed", "detail": "A credit was proposed and is waiting."},
            )
        ]
    if name == "treatment_step":
        return [
            _one(
                publisher,
                session,
                "treatment.actions",
                {**base, "eventType": "treatment.step", "detail": "Reminder step recorded."},
            )
        ]
    if name == "entitlement_changed":
        return [
            _one(
                publisher,
                session,
                "entitlement.changes",
                {**base, "eventType": "entitlement.changed", "detail": "Allowance reset recorded."},
            )
        ]
    if name == "provisioning_mismatch":
        return [
            _one(
                publisher,
                session,
                "provisioning.events",
                {
                    **base,
                    "eventType": "provisioning.mismatch",
                    "detail": "The network profile does not match the entitled pack.",
                },
            )
        ]
    if name == "entitlement_mismatch":
        return [
            _one(
                publisher,
                session,
                "entitlement.changes",
                {
                    **base,
                    "eventType": "entitlement.mismatch",
                    "detail": "The catalogue entitlement is missing on the subscription.",
                },
            )
        ]
    if name == "poison":
        return [
            _one(
                publisher,
                session,
                "system.errors",
                {
                    **base,
                    "eventType": "system.error.poison",
                    "detail": "Synthetic poison event for the dead-letter queue.",
                },
            )
        ]
    if name == "bill_run_failed":
        run_key = f"run-{uuid.uuid4().hex[:12]}"
        started = _one(
            publisher,
            session,
            "bill.run",
            {**base, "eventType": "bill.run.started", "runKey": run_key, "detail": "Bill run started."},
        )
        failed = _one(
            publisher,
            session,
            "bill.run",
            {
                **base,
                "eventType": "bill.run.failed",
                "runKey": run_key,
                "error": "Invoice dispatch did not acknowledge the batch.",
                "detail": "Invoice dispatch did not acknowledge the batch.",
            },
        )
        return [started, failed]
    run_key = f"stuck-{uuid.uuid4().hex[:12]}"
    return [
        _one(
            publisher,
            session,
            "bill.run",
            {
                **base,
                "eventType": "bill.run.started",
                "runKey": run_key,
                "occurredAt": past.isoformat(),
                "detail": "Bill run started and was not closed.",
            },
        )
    ]


def _one(publisher: OutboxPublisher, session: Session, topic: str, payload: dict) -> str:
    return publisher.publish(topic, payload, session=session)
