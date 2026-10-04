"""Every write lands in audit_log, with the request id from the caller or the middleware."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import Request
from sqlalchemy.orm import Session

from billpilot.api.security import Principal
from billpilot.models import AuditLog


def json_safe(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def append_audit(
    session: Session,
    *,
    role: str,
    actor_id: str,
    request_id: str,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    account_id: uuid.UUID | None,
    payload: dict,
) -> AuditLog:
    row = AuditLog(
        id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        actor_role=role,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        account_id=account_id,
        payload=json_safe(payload),
    )
    session.add(row)
    return row


def write_audit(
    session: Session,
    principal: Principal,
    request: Request,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    account_id: uuid.UUID | None,
    payload: dict,
) -> AuditLog:
    return append_audit(
        session,
        role=principal.role,
        actor_id=principal.actor_id,
        request_id=request.state.request_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        account_id=account_id,
        payload=payload,
    )
