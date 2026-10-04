"""Ops actions on a finding. A case is a ticket. A credit stays pending approval."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from billpilot.api.audit import append_audit
from billpilot.api.security import Principal
from billpilot.billing import credit_for_removing
from billpilot.models import Adjustment, Invoice, RaFinding, Ticket


def open_case(session: Session, finding: RaFinding, principal: Principal, request_id: str) -> tuple[Ticket, bool]:
    if finding.ticket_id is not None:
        ticket = session.get(Ticket, finding.ticket_id)
        if ticket is not None:
            return ticket, True
    now = datetime.now(UTC)
    ticket = Ticket(
        id=uuid.uuid4(),
        account_id=finding.account_id,
        ticket_number=f"TCK-RA-{uuid.uuid4().hex[:10].upper()}",
        ticket_type="revenue_assurance",
        severity="Major",
        status="open",
        summary=finding.summary[:200],
        description=(
            f"{finding.name if hasattr(finding, 'name') else finding.summary} "
            f"Detector {finding.detector}. Evidence is on the finding. This case does not move money."
        ),
        opened_by=principal.actor_id,
        opened_at=now,
    )
    session.add(ticket)
    session.flush()
    finding.ticket_id = ticket.id
    finding.status = "case_opened"
    append_audit(
        session,
        role=principal.role,
        actor_id=principal.actor_id,
        request_id=request_id,
        action="finding.case",
        resource_type="ticket",
        resource_id=ticket.id,
        account_id=finding.account_id,
        payload={"findingId": str(finding.id), "detector": finding.detector, "status": "open"},
    )
    return ticket, False


def propose_adjustment(
    session: Session, finding: RaFinding, principal: Principal, request_id: str
) -> tuple[Adjustment, bool]:
    if finding.adjustment_id is not None:
        existing = session.get(Adjustment, finding.adjustment_id)
        if existing is not None:
            return existing, True
    evidence = finding.evidence or {}
    raw = evidence.get("pre_tax_amount") or evidence.get("preTaxAmount")
    if raw is None:
        raise ValueError("This finding has no amount to credit. Open a case instead.")
    pre_tax = Decimal(str(raw))
    if pre_tax <= 0:
        raise ValueError("This finding has no positive amount to credit. Open a case instead.")
    invoice_id = evidence.get("invoice_id") or evidence.get("invoiceId")
    invoice = session.get(Invoice, uuid.UUID(str(invoice_id))) if invoice_id else None
    if invoice is None or invoice.account_id != finding.account_id:
        invoice = session.scalar(
            select(Invoice)
            .where(Invoice.account_id == finding.account_id)
            .order_by(Invoice.period_end.desc(), Invoice.id)
            .limit(1)
        )
    if invoice is None:
        raise ValueError("This account has no invoice to adjust.")
    amount = credit_for_removing(invoice.subtotal, invoice.total, pre_tax)
    if amount <= 0:
        raise ValueError("The computed credit is zero. Open a case instead.")
    now = datetime.now(UTC)
    adjustment = Adjustment(
        id=uuid.uuid4(),
        account_id=finding.account_id,
        invoice_id=invoice.id,
        invoice_line_id=None,
        dispute_id=None,
        adjustment_type="credit",
        amount=amount,
        currency="INR",
        reason=f"{finding.summary} Pending review, not applied.",
        status="pending_approval",
        proposed_by=principal.actor_id,
        decided_by=None,
        proposed_at=now,
        decided_at=None,
        applied_at=None,
        decision_note=None,
        evidence={"findingId": str(finding.id), "detector": finding.detector, "preTaxAmount": f"{pre_tax:.2f}"},
    )
    session.add(adjustment)
    session.flush()
    finding.adjustment_id = adjustment.id
    finding.status = "adjustment_proposed"
    append_audit(
        session,
        role=principal.role,
        actor_id=principal.actor_id,
        request_id=request_id,
        action="finding.propose_adjustment",
        resource_type="adjustment",
        resource_id=adjustment.id,
        account_id=finding.account_id,
        payload={"findingId": str(finding.id), "amount": f"{amount:.2f}", "status": "pending_approval"},
    )
    session.flush()
    return adjustment, False
