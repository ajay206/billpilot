"""Ops failure dashboard, reports, and revenue-assurance actions.

Every route uses require_roles, the same dependency the session-login work will
keep calling. Customers cannot call these. CSR can read incidents for accounts
in scope, which the troubleshooting assistant needs.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from billpilot.api.access import require_account, scope_accounts
from billpilot.api.audit import append_audit, write_audit
from billpilot.api.security import Principal, require_roles
from billpilot.db import get_session
from billpilot.models import BillRun, DeadLetter, Incident, RaFinding, ReportRun
from billpilot.ops.actions import open_case, propose_adjustment
from billpilot.ops.detectors import DETECTORS, detect, persist_findings
from billpilot.ops.pipeline import lag_snapshot, replay_dead_letter
from billpilot.ops.reports import REPORT_KEYS, generate_report, generate_scheduled, report_csv
from billpilot.ops.simulate import SCENARIOS, simulate

router = APIRouter()

_NAMES = {(item["detector"], item["anomaly_type"]): item for item in DETECTORS}


class SimulateBody(BaseModel):
    scenarios: list[str] | None = None


class ReportBody(BaseModel):
    reportKey: str | None = None
    grain: str | None = None
    periodStart: date | None = None
    periodEnd: date | None = None


def _incident(row: Incident) -> dict:
    return {
        "id": str(row.id),
        "incidentType": row.incident_type,
        "severity": row.severity,
        "status": row.status,
        "title": row.title,
        "description": row.description,
        "detectedAt": row.detected_at.isoformat(),
        "accountId": None if row.account_id is None else str(row.account_id),
        "relatedEntityType": row.related_entity_type,
        "relatedEntityId": None if row.related_entity_id is None else str(row.related_entity_id),
        "evidence": row.evidence or {},
    }


def _finding(row: RaFinding) -> dict:
    spec = _NAMES.get((row.detector, row.anomaly_type), {})
    return {
        "id": str(row.id),
        "detector": row.detector,
        "anomalyType": row.anomaly_type,
        "name": spec.get("name", row.detector),
        "family": spec.get("family", "revenue"),
        "severity": row.severity,
        "status": row.status,
        "summary": row.summary,
        "evidence": row.evidence or {},
        "accountId": str(row.account_id),
        "detectedAt": row.detected_at.isoformat(),
        "ticketId": None if row.ticket_id is None else str(row.ticket_id),
        "adjustmentId": None if row.adjustment_id is None else str(row.adjustment_id),
    }


def _report(row: ReportRun) -> dict:
    return {
        "id": str(row.id),
        "reportKey": row.report_key,
        "grain": row.grain,
        "periodStart": row.period_start.isoformat(),
        "periodEnd": row.period_end.isoformat(),
        "generatedAt": row.generated_at.isoformat(),
        "generatedBy": row.generated_by,
        "rowCount": row.row_count,
        "payload": row.payload,
    }


def _run(row: BillRun) -> dict:
    return {
        "id": str(row.id),
        "runKey": row.run_key,
        "accountId": None if row.account_id is None else str(row.account_id),
        "status": row.status,
        "startedAt": row.started_at.isoformat(),
        "finishedAt": None if row.finished_at is None else row.finished_at.isoformat(),
        "error": row.error,
    }


def _letter(row: DeadLetter) -> dict:
    return {
        "id": str(row.id),
        "outboxEventId": str(row.outbox_event_id),
        "topic": row.topic,
        "eventType": row.event_type,
        "error": row.error,
        "retryCount": row.retry_count,
        "status": row.status,
        "replayEventId": None if row.replay_event_id is None else str(row.replay_event_id),
        "createdAt": row.created_at.isoformat(),
        "payload": row.payload,
    }


@router.get("/ops/failures", tags=["Operations"])
def failure_snapshot(
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    del principal
    incidents = session.scalars(select(Incident).order_by(Incident.detected_at.desc()).limit(80)).all()
    stuck = session.scalars(select(BillRun).where(BillRun.status == "stuck").order_by(BillRun.started_at.desc())).all()
    letters = session.scalars(select(DeadLetter).order_by(DeadLetter.created_at.desc()).limit(40)).all()
    transport = getattr(request.app.state.publisher, "transport", None)
    return {
        "backend": request.app.state.settings.event_backend,
        "incidents": [_incident(row) for row in incidents],
        "stuckRuns": [_run(row) for row in stuck],
        "deadLetters": [_letter(row) for row in letters],
        "lag": lag_snapshot(session, request.app.state.settings, transport),
    }


@router.get("/ops/incidents", tags=["Operations"])
def list_incidents(
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("csr", "ops")),
    account_id: uuid.UUID | None = Query(None, alias="accountId"),
    limit: int = Query(20, ge=1, le=100),
):
    stmt = select(Incident)
    if account_id is not None:
        require_account(session, principal, account_id)
        stmt = stmt.where(Incident.account_id == account_id)
    stmt = scope_accounts(stmt, Incident.account_id, session, principal)
    rows = session.scalars(stmt.order_by(Incident.detected_at.desc()).limit(limit)).all()
    return [_incident(row) for row in rows]


@router.post("/ops/faults/simulate", tags=["Operations"])
def simulate_faults(
    body: SimulateBody,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    try:
        event_ids = simulate(
            session,
            request.app.state.publisher,
            request.app.state.settings,
            body.scenarios,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    batch_id = uuid.uuid4()
    append_audit(
        session,
        role=principal.role,
        actor_id=principal.actor_id,
        request_id=request.state.request_id,
        action="faults.simulate",
        resource_type="incident",
        resource_id=batch_id,
        account_id=None,
        payload={"scenarios": body.scenarios or list(SCENARIOS), "eventIds": event_ids},
    )
    session.commit()
    return {"eventIds": event_ids, "scenarios": body.scenarios or list(SCENARIOS)}


@router.post("/ops/deadLetters/{letter_id}/replay", tags=["Operations"])
def replay_letter(
    letter_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    try:
        row, duplicate = replay_dead_letter(session, letter_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dead letter not found.") from exc
    if not duplicate:
        write_audit(
            session,
            principal,
            request,
            "dead_letter.replay",
            "dead_letter",
            letter_id,
            row.account_id,
            {"replayEventId": str(row.id), "eventType": row.event_type},
        )
    session.commit()
    from billpilot.ops.pipeline import drain

    drain(session, request.app.state.settings, getattr(request.app.state.publisher, "transport", None))
    return {"deadLetterId": str(letter_id), "replayEventId": str(row.id), "duplicate": duplicate}


@router.get("/ops/reports", tags=["Operations"])
def list_reports(
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    del principal
    rows = session.scalars(select(ReportRun).order_by(ReportRun.generated_at.desc()).limit(40)).all()
    return [_report(row) for row in rows]


@router.post("/ops/reports/generate", tags=["Operations"])
def generate_reports(
    body: ReportBody,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    try:
        if body.grain and body.periodStart and body.periodEnd:
            keys = [body.reportKey] if body.reportKey else list(REPORT_KEYS)
            saved = [
                generate_report(session, key, body.grain, body.periodStart, body.periodEnd, principal.actor_id)
                for key in keys
            ]
        elif body.reportKey or body.grain or body.periodStart or body.periodEnd:
            raise ValueError("Pass reportKey, grain, periodStart, and periodEnd together, or pass nothing.")
        else:
            saved = generate_scheduled(session, principal.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    batch_id = uuid.uuid4() if not saved else saved[0].id
    append_audit(
        session,
        role=principal.role,
        actor_id=principal.actor_id,
        request_id=request.state.request_id,
        action="reports.generate",
        resource_type="report",
        resource_id=batch_id,
        account_id=None,
        payload={"reportIds": [str(row.id) for row in saved]},
    )
    session.commit()
    return [_report(row) for row in saved]


@router.get("/ops/reports/{report_id}", tags=["Operations"])
def get_report(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    del principal
    row = session.get(ReportRun, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return _report(row)


@router.get("/ops/reports/{report_id}/csv", tags=["Operations"])
def report_download(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    del principal
    row = session.get(ReportRun, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    filename = f"{row.report_key}-{row.grain}-{row.period_start.isoformat()}.csv"
    return Response(
        content=report_csv(row.payload),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/ops/assurance/run", tags=["Operations"])
def run_assurance(
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    findings = detect(session)
    stored = persist_findings(session, findings)
    batch_id = stored[0].id if stored else uuid.uuid4()
    append_audit(
        session,
        role=principal.role,
        actor_id=principal.actor_id,
        request_id=request.state.request_id,
        action="assurance.run",
        resource_type="finding",
        resource_id=batch_id,
        account_id=None,
        payload={"findings": len(stored)},
    )
    session.commit()
    return {"findings": len(stored), "rows": [_finding(row) for row in stored]}


@router.get("/ops/findings", tags=["Operations"])
def list_findings(
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
    account_id: uuid.UUID | None = Query(None, alias="accountId"),
):
    del principal
    stmt = select(RaFinding)
    if account_id is not None:
        stmt = stmt.where(RaFinding.account_id == account_id)
    rows = session.scalars(stmt.order_by(RaFinding.detected_at.desc()).limit(200)).all()
    return [_finding(row) for row in rows]


@router.post("/ops/findings/{finding_id}/case", tags=["Operations"])
def finding_case(
    finding_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    finding = session.get(RaFinding, finding_id, with_for_update=True)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    ticket, duplicate = open_case(session, finding, principal, request.state.request_id)
    session.commit()
    return {
        "duplicate": duplicate,
        "ticketId": str(ticket.id),
        "ticketNumber": ticket.ticket_number,
        "status": ticket.status,
        "finding": _finding(finding),
    }


@router.post("/ops/findings/{finding_id}/adjustment", tags=["Operations"])
def finding_adjustment(
    finding_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    finding = session.get(RaFinding, finding_id, with_for_update=True)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    try:
        adjustment, duplicate = propose_adjustment(session, finding, principal, request.state.request_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    request.app.state.publisher.publish(
        "payment.events",
        {
            "eventType": "adjustment.proposed",
            "accountId": str(adjustment.account_id),
            "adjustmentId": str(adjustment.id),
            "amount": f"{adjustment.amount:.2f}",
            "detail": "Ops proposed a credit from a revenue-assurance finding. It is pending approval.",
        },
        session=session,
    )
    session.commit()
    return {
        "duplicate": duplicate,
        "adjustmentId": str(adjustment.id),
        "status": adjustment.status,
        "amount": f"{adjustment.amount:.2f}",
        "finding": _finding(finding),
    }
