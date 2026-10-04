"""Daily and monthly reports. Every figure is a SQL aggregate over the ledger."""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from billpilot.models import ReportRun

REPORT_KEYS: tuple[str, ...] = (
    "billing",
    "collections",
    "disputes",
    "payments",
    "agent",
)


def _ready(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _rows(session: Session, sql: str, start: date, end: date) -> list[dict]:
    result = session.execute(text(sql), {"start": start, "end": end}).mappings().all()
    return [{key: _ready(row[key]) for key in row.keys()} for row in result]


def _billing(session: Session, start: date, end: date) -> dict:
    rows = _rows(
        session,
        """
        SELECT issue_date::text AS issue_date,
               COUNT(*) AS invoice_count,
               COALESCE(SUM(subtotal), 0) AS subtotal,
               COALESCE(SUM(tax), 0) AS tax,
               COALESCE(SUM(total), 0) AS total,
               COALESCE(SUM(amount_due), 0) AS amount_due
        FROM invoices
        WHERE issue_date >= :start AND issue_date < :end
        GROUP BY issue_date
        ORDER BY issue_date
        """,
        start,
        end,
    )
    totals = _rows(
        session,
        """
        SELECT COUNT(*) AS invoice_count,
               COALESCE(SUM(subtotal), 0) AS subtotal,
               COALESCE(SUM(tax), 0) AS tax,
               COALESCE(SUM(total), 0) AS total,
               COALESCE(SUM(amount_due), 0) AS amount_due
        FROM invoices
        WHERE issue_date >= :start AND issue_date < :end
        """,
        start,
        end,
    )
    return {
        "columns": ["issue_date", "invoice_count", "subtotal", "tax", "total", "amount_due"],
        "rows": rows,
        "totals": totals[0],
    }


def _collections(session: Session, start: date, end: date) -> dict:
    stages = _rows(
        session,
        """
        SELECT stage, status, COUNT(*) AS accounts
        FROM account_treatment
        WHERE :start <= :end
        GROUP BY stage, status
        ORDER BY stage, status
        """,
        start,
        end,
    )
    events = _rows(
        session,
        """
        SELECT event_type, COUNT(*) AS events
        FROM dunning_events
        WHERE occurred_at >= :start AND occurred_at < :end
        GROUP BY event_type
        ORDER BY event_type
        """,
        start,
        end,
    )
    rows = [{"section": "treatment", **row} for row in stages] + [{"section": "dunning", **row} for row in events]
    return {
        "columns": ["section", "stage", "status", "accounts", "event_type", "events"],
        "rows": rows,
        "totals": {"treatment_rows": len(stages), "dunning_rows": len(events)},
    }


def _disputes(session: Session, start: date, end: date) -> dict:
    disputes = _rows(
        session,
        """
        SELECT status, COUNT(*) AS disputes
        FROM disputes
        WHERE opened_at >= :start AND opened_at < :end
        GROUP BY status
        ORDER BY status
        """,
        start,
        end,
    )
    credits = _rows(
        session,
        """
        SELECT status,
               adjustment_type,
               COUNT(*) AS adjustments,
               COALESCE(SUM(amount), 0) AS amount
        FROM adjustments
        WHERE proposed_at >= :start AND proposed_at < :end
        GROUP BY status, adjustment_type
        ORDER BY status, adjustment_type
        """,
        start,
        end,
    )
    rows = [{"section": "disputes", **row} for row in disputes] + [{"section": "adjustments", **row} for row in credits]
    return {
        "columns": ["section", "status", "disputes", "adjustment_type", "adjustments", "amount"],
        "rows": rows,
        "totals": {"dispute_groups": len(disputes), "adjustment_groups": len(credits)},
    }


def _payments(session: Session, start: date, end: date) -> dict:
    payments = _rows(
        session,
        """
        SELECT status, COUNT(*) AS payments, COALESCE(SUM(amount), 0) AS amount
        FROM payments
        WHERE received_at >= :start AND received_at < :end
        GROUP BY status
        ORDER BY status
        """,
        start,
        end,
    )
    attempts = _rows(
        session,
        """
        SELECT status, COUNT(*) AS attempts, COALESCE(SUM(amount), 0) AS amount
        FROM payment_attempts
        WHERE attempted_at >= :start AND attempted_at < :end
        GROUP BY status
        ORDER BY status
        """,
        start,
        end,
    )
    rows = [{"section": "payments", **row} for row in payments] + [{"section": "attempts", **row} for row in attempts]
    return {
        "columns": ["section", "status", "payments", "attempts", "amount"],
        "rows": rows,
        "totals": {"payment_groups": len(payments), "attempt_groups": len(attempts)},
    }


def _agent(session: Session, start: date, end: date) -> dict:
    rows = _rows(
        session,
        """
        SELECT persona,
               COUNT(*) AS turns,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
        FROM agent_runs
        WHERE occurred_at >= :start AND occurred_at < :end
        GROUP BY persona
        ORDER BY persona
        """,
        start,
        end,
    )
    totals = _rows(
        session,
        """
        SELECT COUNT(*) AS turns,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
        FROM agent_runs
        WHERE occurred_at >= :start AND occurred_at < :end
        """,
        start,
        end,
    )
    return {
        "columns": ["persona", "turns", "prompt_tokens", "completion_tokens", "estimated_cost_usd"],
        "rows": rows,
        "totals": totals[0],
    }


_BUILDERS = {
    "billing": _billing,
    "collections": _collections,
    "disputes": _disputes,
    "payments": _payments,
    "agent": _agent,
}


def scheduled_windows(session: Session) -> list[tuple[str, date, date]]:
    """The latest invoice day and that month. Empty when the ledger has no bills."""
    latest = session.scalar(text("SELECT MAX(issue_date) FROM invoices"))
    if latest is None:
        return []
    month_start = latest.replace(day=1)
    if month_start.month == 12:
        month_end = date(month_start.year + 1, 1, 1)
    else:
        month_end = date(month_start.year, month_start.month + 1, 1)
    return [("daily", latest, latest + timedelta(days=1)), ("monthly", month_start, month_end)]


def generate_report(
    session: Session,
    report_key: str,
    grain: str,
    start: date,
    end: date,
    generated_by: str,
) -> ReportRun:
    if report_key not in _BUILDERS:
        raise ValueError(f"Unknown report {report_key}")
    if grain not in {"daily", "monthly"}:
        raise ValueError("grain must be daily or monthly")
    if end <= start:
        raise ValueError("period end must be after period start")
    payload = _BUILDERS[report_key](session, start, end)
    now = datetime.now(UTC)
    existing = session.scalar(
        select(ReportRun).where(
            ReportRun.report_key == report_key,
            ReportRun.grain == grain,
            ReportRun.period_start == start,
            ReportRun.period_end == end,
        )
    )
    if existing is None:
        existing = ReportRun(
            id=uuid.uuid4(),
            report_key=report_key,
            grain=grain,
            period_start=start,
            period_end=end,
            generated_at=now,
            generated_by=generated_by,
            row_count=len(payload["rows"]),
            payload=payload,
        )
        session.add(existing)
    else:
        existing.generated_at = now
        existing.generated_by = generated_by
        existing.row_count = len(payload["rows"])
        existing.payload = payload
    session.commit()
    session.refresh(existing)
    return existing


def generate_scheduled(session: Session, generated_by: str) -> list[ReportRun]:
    windows = scheduled_windows(session)
    saved: list[ReportRun] = []
    for grain, start, end in windows:
        for key in REPORT_KEYS:
            saved.append(generate_report(session, key, grain, start, end, generated_by))
    return saved


def report_csv(payload: dict) -> str:
    columns = list(payload.get("columns") or [])
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in payload.get("rows") or []:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()
