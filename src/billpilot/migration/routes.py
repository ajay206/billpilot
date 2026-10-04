"""Ops migration desk. Loading and dry run do not write billing rows.

Commit and rollback are one transaction each. The API process stays up; the
batch does not take an exclusive lock on the ledger.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from billpilot.api.audit import write_audit
from billpilot.api.security import Principal, require_roles
from billpilot.db import get_session
from billpilot.migration.legacy import parse_records, render_json, sample_records
from billpilot.migration.pipeline import (
    MigrationError,
    batch_records,
    commit_batch,
    dry_run,
    latest_batch,
    list_batches,
    load_batch,
    reconciliation_csv,
    record_dict,
    rejects_for,
    require_batch,
    rollback_batch,
    sign_off,
)
from billpilot.onboarding.provision import ProvisionError

router = APIRouter(prefix="/ops/migration", tags=["Migration"])


class BatchCreate(BaseModel):
    source: str = "sample"
    name: str | None = Field(default=None, max_length=200)
    body: str | None = None


class SignOff(BaseModel):
    approveMapping: bool = False


def _fail(exc: MigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _view(session: Session, batch, *, detail: bool) -> dict:
    records = batch_records(session, batch.id) if detail else []
    body = {
        "id": str(batch.id),
        "batchCode": batch.batch_code,
        "status": batch.status,
        "sourceName": batch.source_name,
        "sourceFormat": batch.source_format,
        "mappingVersion": batch.mapping_version,
        "createdBy": batch.created_by,
        "createdAt": batch.created_at.isoformat(),
        "signedOffBy": batch.signed_off_by,
        "summary": batch.summary,
        "balanceMatched": (batch.summary or {}).get("balanceMatched"),
    }
    if detail:
        body["records"] = [record_dict(row) for row in records]
        body["mappingSuggestions"] = (batch.summary or {}).get("mappingSuggestions", [])
        body["csv"] = reconciliation_csv(batch, records)
    return body


def _audit(session, principal, request, action, batch, payload) -> None:
    write_audit(
        session,
        principal,
        request,
        action,
        "migration_batch",
        batch.id,
        None,
        payload,
    )


@router.get("/batches")
def get_batches(
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    del principal
    rows, total = list_batches(session, offset=offset, limit=limit)
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Result-Count"] = str(len(rows))
    return [_view(session, row, detail=False) for row in rows]


@router.post("/batches", status_code=201)
def create_batch(
    body: BatchCreate,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    try:
        if body.source == "sample":
            records = parse_records(render_json(sample_records()), "json")
            name = body.name or "synthetic-sample"
            source_format = "json"
        elif body.source in {"csv", "json"}:
            if not body.body:
                raise MigrationError(422, "Upload a file body, or choose the synthetic sample.")
            records = parse_records(body.body, body.source)
            name = body.name or f"upload.{body.source}"
            source_format = body.source
        else:
            raise MigrationError(422, "source must be sample, csv, or json.")
        batch = load_batch(
            session,
            records=records,
            source_name=name,
            source_format=source_format,
            actor=principal.actor_id,
        )
    except MigrationError as exc:
        raise _fail(exc) from exc
    except ProvisionError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(session, principal, request, "migration.load", batch, {"sourceName": batch.source_name, "writes": 0})
    session.commit()
    return _view(session, batch, detail=True)


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: uuid.UUID,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    del principal
    try:
        batch = require_batch(session, batch_id)
    except MigrationError as exc:
        raise _fail(exc) from exc
    return _view(session, batch, detail=True)


@router.post("/batches/{batch_id}/dry-run")
def post_dry_run(
    batch_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    try:
        batch = dry_run(session, batch_id)
    except MigrationError as exc:
        raise _fail(exc) from exc
    _audit(
        session,
        principal,
        request,
        "migration.dry_run",
        batch,
        {"status": batch.status, "rejected": (batch.summary or {}).get("rejected"), "writes": 0},
    )
    session.commit()
    return _view(session, batch, detail=True)


@router.post("/batches/{batch_id}/sign-off")
def post_sign_off(
    batch_id: uuid.UUID,
    body: SignOff,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    if not body.approveMapping:
        raise HTTPException(status_code=422, detail="Set approveMapping to true to sign off the plan mapping.")
    try:
        batch = sign_off(session, batch_id, principal.actor_id)
    except MigrationError as exc:
        raise _fail(exc) from exc
    _audit(session, principal, request, "migration.sign_off", batch, {"mappingVersion": batch.mapping_version})
    session.commit()
    return _view(session, batch, detail=True)


@router.post("/batches/{batch_id}/commit")
def post_commit(
    batch_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    try:
        summary = commit_batch(session, batch_id, principal.actor_id)
        batch = require_batch(session, batch_id)
        _audit(
            session,
            principal,
            request,
            "migration.commit",
            batch,
            {
                "idempotent": summary.get("idempotent", False),
                "writes": summary.get("writes", 0),
                "balanceMatched": summary.get("balanceMatched"),
            },
        )
        session.commit()
    except MigrationError as exc:
        session.rollback()
        raise _fail(exc) from exc
    except ProvisionError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A row in this batch collides with the live ledger. Dry-run again. Nothing was committed.",
        ) from exc
    request.app.state.publisher.publish(
        "entitlement.changes",
        {"action": "migrated", "batchId": str(batch.id), "writes": summary.get("writes", 0)},
    )
    request.app.state.publisher.publish(
        "treatment.actions",
        {"action": "opened", "batchId": str(batch.id), "stage": "none"},
    )
    return _view(session, batch, detail=True)


@router.post("/batches/{batch_id}/rollback")
def post_rollback(
    batch_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    try:
        summary = rollback_batch(session, batch_id)
        batch = require_batch(session, batch_id)
        _audit(
            session,
            principal,
            request,
            "migration.rollback",
            batch,
            {"restored": True, "alreadyRolledBack": summary.get("alreadyRolledBack", False)},
        )
        session.commit()
    except MigrationError as exc:
        session.rollback()
        raise _fail(exc) from exc
    request.app.state.publisher.publish(
        "entitlement.changes",
        {"action": "migration_rolled_back", "batchId": str(batch.id)},
    )
    return _view(session, batch, detail=True)


@router.get("/batches/{batch_id}/rejects")
def get_rejects(
    batch_id: uuid.UUID,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    del principal
    try:
        batch = require_batch(session, batch_id)
    except MigrationError as exc:
        raise _fail(exc) from exc
    return rejects_for(batch_records(session, batch.id), batch)


@router.get("/rejects")
def get_latest_rejects(
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> dict:
    """Latest batch rejects. An empty ledger is an empty list, not a 404, so a read tool can answer."""
    del principal
    batch = latest_batch(session)
    if batch is None:
        return {"batchId": None, "batchCode": None, "status": None, "rejects": [], "byReason": {}}
    return rejects_for(batch_records(session, batch.id), batch)


@router.get("/batches/{batch_id}/reconciliation.csv")
def get_csv(
    batch_id: uuid.UUID,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
) -> Response:
    del principal
    try:
        batch = require_batch(session, batch_id)
    except MigrationError as exc:
        raise _fail(exc) from exc
    records = batch_records(session, batch.id)
    content = reconciliation_csv(batch, records)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{batch.batch_code}-reconciliation.csv"'},
    )
