"""TMF-shaped resources. Reads are filtered by persona. Writes are the Phase 2 seams.

Creating a dispute or a ticket, and proposing an adjustment, are the only writes.
An adjustment is inserted as pending_approval. The approve endpoint is the only
way it changes a bill, and the caller cannot be the person who proposed it.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from billpilot.api.access import account_for_subscription, require_account, scope_accounts
from billpilot.api.audit import write_audit
from billpilot.api.present import (
    to_adjustment,
    to_attempt,
    to_audit,
    to_bill,
    to_billing_account,
    to_bucket,
    to_dispute,
    to_entitlement_product,
    to_fraud_flag,
    to_offering,
    to_payment,
    to_rate,
    to_subscription_product,
    to_ticket,
    to_usage,
    to_vas_product,
)
from billpilot.api.schemas import (
    AdjustmentCreate,
    AppliedRate,
    ApprovalDecision,
    AuditEntry,
    BillAdjustment,
    BillingAccount,
    Bucket,
    CustomerBill,
    CustomerBillDispute,
    DisputeCreate,
    FraudFlagView,
    Payment,
    PaymentAttempt,
    Product,
    ProductOffering,
    TicketCreate,
    TroubleTicket,
    Usage,
)
from billpilot.api.security import Principal, get_principal, require_roles
from billpilot.billing import ZERO, money
from billpilot.db import get_session
from billpilot.models import (
    Account,
    AccountTreatment,
    Adjustment,
    AuditLog,
    Customer,
    Dispute,
    Entitlement,
    EntitlementBalance,
    FraudFlag,
    Invoice,
    InvoiceLine,
    Subscription,
    TariffPlan,
    Ticket,
    TreatmentExemption,
    UsageEvent,
    VasSubscription,
)
from billpilot.models import (
    Payment as PaymentRow,
)
from billpilot.models import (
    PaymentAttempt as PaymentAttemptRow,
)

router = APIRouter()
audit_router = APIRouter()


def _adjustment_view(request: Request, session: Session, row: Adjustment) -> BillAdjustment:
    account = session.get(Account, row.account_id)
    label = None
    if account is not None:
        customer = session.get(Customer, account.customer_id)
        holder = f"{customer.given_name} {customer.family_name}" if customer is not None else account.account_number
        label = f"{holder} · {account.account_number}"
    return to_adjustment(request, row, label)


_BILL_STATUS = {
    "settled": "paid",
    "partiallyPaid": "partially_paid",
    "sent": "issued",
    "cancelled": "cancelled",
}
_PAYMENT_STATUS = {
    "done": "posted",
    "pending": "received",
    "declined": "reversed",
    "posted": "posted",
    "received": "received",
    "failed": "failed",
    "reversed": "reversed",
}


def _page_headers(response: Response, total: int, count: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Result-Count"] = str(count)


def _count(session: Session, stmt) -> int:
    return session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _day(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO date.") from exc


def _moment(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO date-time.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _account_filter(session, principal, stmt, column, account_id: uuid.UUID | None):
    if account_id is not None:
        require_account(session, principal, account_id)
        return stmt.where(column == account_id)
    return scope_accounts(stmt, column, session, principal)


# --- TMF678 Customer Bill -------------------------------------------------


@router.get("/customerBillManagement/v4/customerBill", response_model=list[CustomerBill], tags=["TMF678 Customer Bill"])
def list_bills(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    state: str | None = None,
    bill_no: str | None = Query(None, alias="billNo"),
    bill_date_gte: str | None = Query(None, alias="billDate.gte"),
    bill_date_lte: str | None = Query(None, alias="billDate.lte"),
):
    stmt = _account_filter(session, principal, select(Invoice), Invoice.account_id, account_id)
    if state is not None:
        status = _BILL_STATUS.get(state)
        if status is None:
            raise HTTPException(status_code=422, detail="state must be sent, partiallyPaid, settled or cancelled.")
        stmt = stmt.where(Invoice.status == status)
    if bill_no:
        stmt = stmt.where(Invoice.bill_number == bill_no)
    if bill_date_gte:
        stmt = stmt.where(Invoice.issue_date >= _day(bill_date_gte, "billDate.gte"))
    if bill_date_lte:
        stmt = stmt.where(Invoice.issue_date <= _day(bill_date_lte, "billDate.lte"))
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(Invoice.issue_date.desc(), Invoice.id).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    return [to_bill(request, session, row) for row in rows]


@router.get(
    "/customerBillManagement/v4/customerBill/{bill_id}",
    response_model=CustomerBill,
    tags=["TMF678 Customer Bill"],
)
def get_bill(
    bill_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    invoice = session.get(Invoice, bill_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Customer bill not found.")
    require_account(session, principal, invoice.account_id)
    return to_bill(request, session, invoice)


@router.get(
    "/customerBillManagement/v4/appliedCustomerBillingRate",
    response_model=list[AppliedRate],
    tags=["TMF678 Customer Bill"],
)
def list_rates(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    bill_id: uuid.UUID | None = Query(None, alias="bill.id"),
):
    stmt = select(InvoiceLine, Invoice).join(Invoice, InvoiceLine.invoice_id == Invoice.id)
    stmt = _account_filter(session, principal, stmt, Invoice.account_id, account_id)
    if bill_id is not None:
        invoice = session.get(Invoice, bill_id)
        if invoice is None:
            raise HTTPException(status_code=404, detail="Customer bill not found.")
        require_account(session, principal, invoice.account_id)
        stmt = stmt.where(InvoiceLine.invoice_id == bill_id)
    total = _count(session, stmt)
    rows = session.execute(
        stmt.order_by(Invoice.issue_date.desc(), InvoiceLine.line_number).offset(offset).limit(limit)
    ).all()
    _page_headers(response, total, len(rows))
    return [to_rate(request, session, line, invoice) for line, invoice in rows]


@router.get(
    "/customerBillManagement/v4/customerBillDispute",
    response_model=list[CustomerBillDispute],
    tags=["TMF678 Customer Bill"],
)
def list_disputes(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    status: str | None = None,
):
    stmt = _account_filter(session, principal, select(Dispute), Dispute.account_id, account_id)
    if status:
        stmt = stmt.where(Dispute.status == status)
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(Dispute.opened_at.desc(), Dispute.id).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    return [to_dispute(request, row) for row in rows]


@router.post(
    "/customerBillManagement/v4/customerBillDispute",
    response_model=CustomerBillDispute,
    status_code=201,
    tags=["TMF678 Customer Bill"],
)
def create_dispute(
    body: DisputeCreate,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("customer", "csr")),
):
    account = require_account(session, principal, body.billingAccount.id)
    if body.customerBill is not None:
        invoice = session.get(Invoice, body.customerBill.id)
        if invoice is None or invoice.account_id != account.id:
            raise HTTPException(status_code=422, detail="customerBill is not a bill for this account.")
    else:
        invoice = None
    now = datetime.now(UTC)
    dispute = Dispute(
        id=uuid.uuid4(),
        account_id=account.id,
        invoice_id=None if invoice is None else invoice.id,
        ticket_id=None,
        status="open",
        category=body.category,
        description=body.description,
        opened_by=principal.actor_id,
        opened_at=now,
        resolved_at=None,
    )
    session.add(dispute)
    held = _hold_active_treatment(session, account.id, now, "open_dispute")
    write_audit(
        session,
        principal,
        request,
        "dispute.create",
        "dispute",
        dispute.id,
        account.id,
        {"category": body.category, "treatmentHeld": held},
    )
    request.app.state.publisher.publish(
        "treatment.actions",
        {
            "action": "hold" if held else "dispute_opened",
            "accountId": str(account.id),
            "disputeId": str(dispute.id),
            "reason": "open_dispute",
        },
    )
    session.commit()
    session.refresh(dispute)
    return to_dispute(request, dispute)


@router.get(
    "/customerBillManagement/v4/billAdjustment",
    response_model=list[BillAdjustment],
    tags=["TMF678 Customer Bill"],
)
def list_adjustments(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    status: str | None = None,
):
    stmt = _account_filter(session, principal, select(Adjustment), Adjustment.account_id, account_id)
    if status:
        stmt = stmt.where(Adjustment.status == status)
    total = _count(session, stmt)
    rows = session.scalars(
        stmt.order_by(Adjustment.proposed_at.desc(), Adjustment.id).offset(offset).limit(limit)
    ).all()
    _page_headers(response, total, len(rows))
    return [_adjustment_view(request, session, row) for row in rows]


@router.post(
    "/customerBillManagement/v4/billAdjustment",
    response_model=BillAdjustment,
    status_code=201,
    tags=["TMF678 Customer Bill"],
)
def propose_adjustment(
    body: AdjustmentCreate,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("csr")),
):
    """Propose a credit or debit. It is not applied; status is pending_approval."""
    account = require_account(session, principal, body.billingAccount.id)
    invoice = session.get(Invoice, body.customerBill.id)
    if invoice is None or invoice.account_id != account.id:
        raise HTTPException(status_code=422, detail="customerBill is not a bill for this account.")
    now = datetime.now(UTC)
    adjustment = Adjustment(
        id=uuid.uuid4(),
        account_id=account.id,
        invoice_id=invoice.id,
        invoice_line_id=None,
        dispute_id=None,
        adjustment_type=body.adjustmentType,
        amount=body.amount.value,
        currency="INR",
        reason=body.reason,
        status="pending_approval",
        proposed_by=principal.actor_id,
        decided_by=None,
        proposed_at=now,
        decided_at=None,
        applied_at=None,
        decision_note=None,
        evidence={"invoiceTotalBefore": f"{invoice.total:.2f}", "amountDueBefore": f"{invoice.amount_due:.2f}"},
    )
    session.add(adjustment)
    write_audit(
        session,
        principal,
        request,
        "adjustment.propose",
        "adjustment",
        adjustment.id,
        account.id,
        {
            "adjustmentType": body.adjustmentType,
            "amount": body.amount.value,
            "status": "pending_approval",
            "invoiceId": invoice.id,
        },
    )
    session.commit()
    session.refresh(adjustment)
    return _adjustment_view(request, session, adjustment)


@router.post(
    "/customerBillManagement/v4/billAdjustment/{adjustment_id}/approve",
    response_model=BillAdjustment,
    tags=["TMF678 Customer Bill"],
)
def decide_adjustment(
    adjustment_id: uuid.UUID,
    body: ApprovalDecision,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
):
    """Approve applies the adjustment. Reject leaves the bill unchanged."""
    adjustment = session.get(Adjustment, adjustment_id, with_for_update=True)
    if adjustment is None:
        raise HTTPException(status_code=404, detail="Adjustment not found.")
    require_account(session, principal, adjustment.account_id)
    if adjustment.status != "pending_approval":
        raise HTTPException(status_code=409, detail="Only a pending adjustment can be decided.")
    if adjustment.proposed_by == principal.actor_id:
        raise HTTPException(status_code=403, detail="The proposer cannot approve their own adjustment.")
    now = datetime.now(UTC)
    adjustment.decided_by = principal.actor_id
    adjustment.decided_at = now
    adjustment.decision_note = body.note
    if body.decision == "reject":
        adjustment.status = "rejected"
        write_audit(
            session,
            principal,
            request,
            "adjustment.reject",
            "adjustment",
            adjustment.id,
            adjustment.account_id,
            {"status": "rejected"},
        )
        session.commit()
        session.refresh(adjustment)
        return _adjustment_view(request, session, adjustment)

    invoice = session.get(Invoice, adjustment.invoice_id, with_for_update=True)
    signed = money(-adjustment.amount if adjustment.adjustment_type == "credit" else adjustment.amount)
    new_total = money(invoice.total + signed)
    if new_total < 0:
        raise HTTPException(status_code=422, detail="The adjustment is larger than the invoice total.")
    # Read payments before changing the header. A flush of the new total while
    # amount_due is still the old value would break the amount_due <= total check.
    posted = session.scalar(
        select(func.coalesce(func.sum(PaymentRow.amount), 0)).where(
            PaymentRow.invoice_id == invoice.id,
            PaymentRow.status == "posted",
        )
    )
    next_line = (
        session.scalar(select(func.max(InvoiceLine.line_number)).where(InvoiceLine.invoice_id == invoice.id)) or 0
    )
    session.add(
        InvoiceLine(
            id=uuid.uuid4(),
            invoice_id=invoice.id,
            line_number=next_line + 1,
            charge_type="adjustment",
            description=f"{adjustment.adjustment_type.capitalize()} adjustment",
            quantity=Decimal("1.000"),
            unit_price=adjustment.amount,
            amount=signed,
            subscription_id=None,
            usage_event_id=None,
            tariff_plan_id=None,
        )
    )
    invoice.total = new_total
    invoice.subtotal = money(new_total - invoice.tax)
    posted = money(Decimal(posted))
    invoice.amount_due = money(max(ZERO, invoice.total - posted))
    if invoice.amount_due == 0:
        invoice.status = "paid"
    elif posted > 0:
        invoice.status = "partially_paid"
    else:
        invoice.status = "issued"
    adjustment.status = "applied"
    adjustment.applied_at = now
    write_audit(
        session,
        principal,
        request,
        "adjustment.apply",
        "adjustment",
        adjustment.id,
        adjustment.account_id,
        {
            "status": "applied",
            "amount": adjustment.amount,
            "invoiceId": invoice.id,
            "amountDueAfter": invoice.amount_due,
        },
    )
    request.app.state.publisher.publish(
        "payment.events",
        {
            "kind": "adjustment_applied",
            "adjustmentId": str(adjustment.id),
            "accountId": str(adjustment.account_id),
            "invoiceId": str(invoice.id),
            "amount": f"{adjustment.amount:.2f}",
            "currency": "INR",
        },
    )
    session.commit()
    session.refresh(adjustment)
    return _adjustment_view(request, session, adjustment)


# --- TMF635 Usage ---------------------------------------------------------


@router.get("/usageManagement/v4/usage", response_model=list[Usage], tags=["TMF635 Usage"])
def list_usage(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    product_id: uuid.UUID | None = Query(None, alias="product.id"),
    usage_type: str | None = Query(None, alias="usageType"),
    usage_from: str | None = Query(None, alias="usageDate.gte"),
    usage_to: str | None = Query(None, alias="usageDate.lte"),
):
    stmt = select(UsageEvent).join(Subscription, UsageEvent.subscription_id == Subscription.id)
    stmt = _account_filter(session, principal, stmt, Subscription.account_id, account_id)
    if product_id is not None:
        account_for_subscription(session, principal, product_id)
        stmt = stmt.where(UsageEvent.subscription_id == product_id)
    if usage_type == "roaming":
        stmt = stmt.where(UsageEvent.event_type.like("roaming%"))
    elif usage_type:
        stmt = stmt.where(UsageEvent.event_type == usage_type)
    if usage_from:
        stmt = stmt.where(UsageEvent.started_at >= _moment(usage_from, "usageDate.gte"))
    if usage_to:
        stmt = stmt.where(UsageEvent.started_at <= _moment(usage_to, "usageDate.lte"))
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(UsageEvent.started_at, UsageEvent.id).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    return [to_usage(request, session, row) for row in rows]


@router.get("/usageManagement/v4/usage/{usage_id}", response_model=Usage, tags=["TMF635 Usage"])
def get_usage(
    usage_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    event = session.get(UsageEvent, usage_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Usage not found.")
    account_for_subscription(session, principal, event.subscription_id)
    return to_usage(request, session, event)


# --- TMF620 Product Catalog ----------------------------------------------


@router.get(
    "/productCatalogManagement/v4/productOffering",
    response_model=list[ProductOffering],
    tags=["TMF620 Product Catalog"],
)
def list_offerings(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    name: str | None = None,
    lifecycle_status: str | None = Query(None, alias="lifecycleStatus"),
):
    del principal
    stmt = select(TariffPlan)
    if name:
        stmt = stmt.where(TariffPlan.name.ilike(f"%{name}%"))
    if lifecycle_status:
        stmt = stmt.where(TariffPlan.lifecycle_status == lifecycle_status)
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(TariffPlan.code).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    return [to_offering(request, row) for row in rows]


@router.get(
    "/productCatalogManagement/v4/productOffering/{offering_id}",
    response_model=ProductOffering,
    tags=["TMF620 Product Catalog"],
)
def get_offering(
    offering_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    del principal
    plan = session.get(TariffPlan, offering_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Product offering not found.")
    return to_offering(request, plan)


# --- TMF676 Payment -------------------------------------------------------


@router.get("/paymentManagement/v4/payment", response_model=list[Payment], tags=["TMF676 Payment"])
def list_payments(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="account.id"),
    status: str | None = None,
):
    stmt = _account_filter(session, principal, select(PaymentRow), PaymentRow.account_id, account_id)
    if status:
        internal = _PAYMENT_STATUS.get(status)
        if internal is None:
            raise HTTPException(status_code=422, detail="Unsupported payment status filter.")
        stmt = stmt.where(PaymentRow.status == internal)
    total = _count(session, stmt)
    rows = session.scalars(
        stmt.order_by(PaymentRow.received_at.desc(), PaymentRow.id).offset(offset).limit(limit)
    ).all()
    _page_headers(response, total, len(rows))
    return [to_payment(request, row) for row in rows]


@router.get("/paymentManagement/v4/payment/{payment_id}", response_model=Payment, tags=["TMF676 Payment"])
def get_payment(
    payment_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    row = session.get(PaymentRow, payment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    require_account(session, principal, row.account_id)
    return to_payment(request, row)


@router.get(
    "/paymentManagement/v4/paymentAttempt",
    response_model=list[PaymentAttempt],
    tags=["TMF676 Payment"],
)
def list_attempts(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="account.id"),
    status: str | None = None,
):
    """BillPilot extension. TMF676 does not list attempts that never became payments."""
    stmt = _account_filter(session, principal, select(PaymentAttemptRow), PaymentAttemptRow.account_id, account_id)
    if status:
        stmt = stmt.where(PaymentAttemptRow.status == status)
    total = _count(session, stmt)
    rows = session.scalars(
        stmt.order_by(PaymentAttemptRow.attempted_at, PaymentAttemptRow.id).offset(offset).limit(limit)
    ).all()
    _page_headers(response, total, len(rows))
    return [to_attempt(request, row) for row in rows]


# --- TMF637 Product Inventory --------------------------------------------


def _collect_products(request, session, principal, account_id, product_type):
    products: list[Product] = []
    if product_type in (None, "subscription"):
        stmt = _account_filter(session, principal, select(Subscription), Subscription.account_id, account_id)
        products.extend(to_subscription_product(request, session, row) for row in session.scalars(stmt))
    if product_type in (None, "vas"):
        stmt = select(VasSubscription).join(Subscription, VasSubscription.subscription_id == Subscription.id)
        stmt = _account_filter(session, principal, stmt, Subscription.account_id, account_id)
        products.extend(to_vas_product(request, session, row) for row in session.scalars(stmt))
    if product_type in (None, "entitlement"):
        stmt = select(Entitlement).join(Subscription, Entitlement.subscription_id == Subscription.id)
        stmt = _account_filter(session, principal, stmt, Subscription.account_id, account_id)
        products.extend(to_entitlement_product(request, session, row) for row in session.scalars(stmt))
    products.sort(key=lambda product: product.id)
    return products


@router.get("/productInventory/v4/product", response_model=list[Product], tags=["TMF637 Product Inventory"])
def list_products(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    product_type: str | None = Query(None, alias="productType"),
):
    if product_type not in (None, "subscription", "vas", "entitlement"):
        raise HTTPException(status_code=422, detail="productType must be subscription, vas or entitlement.")
    products = _collect_products(request, session, principal, account_id, product_type)
    _page_headers(response, len(products), len(products[offset : offset + limit]))
    return products[offset : offset + limit]


@router.get("/productInventory/v4/product/{product_id}", response_model=Product, tags=["TMF637 Product Inventory"])
def get_product(
    product_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    subscription = session.get(Subscription, product_id)
    if subscription is not None:
        require_account(session, principal, subscription.account_id)
        return to_subscription_product(request, session, subscription)
    vas = session.get(VasSubscription, product_id)
    if vas is not None:
        parent = session.get(Subscription, vas.subscription_id)
        require_account(session, principal, parent.account_id)
        return to_vas_product(request, session, vas)
    entitlement = session.get(Entitlement, product_id)
    if entitlement is not None:
        parent = session.get(Subscription, entitlement.subscription_id)
        require_account(session, principal, parent.account_id)
        return to_entitlement_product(request, session, entitlement)
    raise HTTPException(status_code=404, detail="Product not found.")


# --- TMF621 Trouble Ticket ------------------------------------------------


@router.get("/troubleTicket/v4/troubleTicket", response_model=list[TroubleTicket], tags=["TMF621 Trouble Ticket"])
def list_tickets(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    status: str | None = None,
):
    stmt = _account_filter(session, principal, select(Ticket), Ticket.account_id, account_id)
    if status:
        internal = {
            value: key
            for key, value in {
                "open": "acknowledged",
                "in_progress": "inProgress",
                "resolved": "resolved",
                "closed": "closed",
            }.items()
        }.get(status, status)
        stmt = stmt.where(Ticket.status == internal)
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(Ticket.opened_at.desc(), Ticket.id).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    return [to_ticket(request, session, row) for row in rows]


@router.post(
    "/troubleTicket/v4/troubleTicket",
    response_model=TroubleTicket,
    status_code=201,
    tags=["TMF621 Trouble Ticket"],
)
def create_ticket(
    body: TicketCreate,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("csr")),
):
    """CSR opens a case. An active collections treatment is held, matching a dispute."""
    account = require_account(session, principal, body.billingAccount.id)
    now = datetime.now(UTC)
    ticket = Ticket(
        id=uuid.uuid4(),
        account_id=account.id,
        ticket_number=f"TCK-{uuid.uuid4().hex[:12].upper()}",
        ticket_type=body.ticketType,
        severity=body.severity,
        status="open",
        summary=body.name,
        description=body.description,
        opened_by=principal.actor_id,
        opened_at=now,
    )
    session.add(ticket)
    held = _hold_active_treatment(session, account.id, now, "open_ticket")
    write_audit(
        session,
        principal,
        request,
        "ticket.create",
        "ticket",
        ticket.id,
        account.id,
        {"ticketType": body.ticketType, "severity": body.severity, "treatmentHeld": held},
    )
    request.app.state.publisher.publish(
        "treatment.actions",
        {
            "action": "hold" if held else "ticket_opened",
            "accountId": str(account.id),
            "ticketId": str(ticket.id),
            "reason": "open_ticket",
        },
    )
    session.commit()
    session.refresh(ticket)
    return to_ticket(request, session, ticket)


def _hold_active_treatment(session: Session, account_id: uuid.UUID, now: datetime, reason: str) -> bool:
    """Pause the open ladder. A hold is not a credit and not a bar removal."""
    treatment = session.scalar(
        select(AccountTreatment).where(
            AccountTreatment.account_id == account_id,
            AccountTreatment.status == "active",
        )
    )
    if treatment is None:
        return False
    treatment.status = "held"
    treatment.hold_reason = reason
    treatment.updated_at = now
    return True


@router.get(
    "/troubleTicket/v4/troubleTicket/{ticket_id}",
    response_model=TroubleTicket,
    tags=["TMF621 Trouble Ticket"],
)
def get_ticket(
    ticket_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Trouble ticket not found.")
    require_account(session, principal, ticket.account_id)
    return to_ticket(request, session, ticket)


# --- TMF654-style balance -------------------------------------------------


@router.get("/prepayBalanceManagement/v4/bucket", response_model=list[Bucket], tags=["TMF654 Balance"])
@router.get("/prepayBalanceManagement/v4/balance", response_model=list[Bucket], tags=["TMF654 Balance"])
def list_buckets(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
    product_id: uuid.UUID | None = Query(None, alias="product.id"),
):
    stmt = (
        select(EntitlementBalance, Entitlement)
        .join(Entitlement, EntitlementBalance.entitlement_id == Entitlement.id)
        .join(Subscription, Entitlement.subscription_id == Subscription.id)
    )
    stmt = _account_filter(session, principal, stmt, Subscription.account_id, account_id)
    if product_id is not None:
        account_for_subscription(session, principal, product_id)
        stmt = stmt.where(Entitlement.subscription_id == product_id)
    total = _count(session, stmt)
    rows = session.execute(
        stmt.order_by(EntitlementBalance.period_start, EntitlementBalance.id).offset(offset).limit(limit)
    ).all()
    _page_headers(response, total, len(rows))
    return [to_bucket(request, balance, entitlement) for balance, entitlement in rows]


# --- Fraud flags ----------------------------------------------------------


@router.get(
    "/accountManagement/v4/fraudFlag",
    response_model=list[FraudFlagView],
    tags=["Billing account"],
)
def list_fraud_flags(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="billingAccount.id"),
):
    """Synthetic roaming-spike and SIM-swap flags. Read-only, scoped like any other account read."""
    stmt = _account_filter(session, principal, select(FraudFlag), FraudFlag.account_id, account_id)
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(FraudFlag.detected_at, FraudFlag.id).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    return [to_fraud_flag(request, row) for row in rows]


# --- Billing account and treatment ----------------------------------------


def _open_treatment(session: Session, account_id: uuid.UUID):
    now = datetime.now(UTC)
    treatment = session.scalar(
        select(AccountTreatment).where(
            AccountTreatment.account_id == account_id,
            AccountTreatment.status.in_(("active", "held")),
        )
    )
    exemption = session.scalars(
        select(TreatmentExemption)
        .where(
            TreatmentExemption.account_id == account_id,
            TreatmentExemption.valid_from <= now,
            TreatmentExemption.valid_to >= now,
        )
        .order_by(TreatmentExemption.valid_from.desc())
    ).first()
    return treatment, exemption


@router.get(
    "/accountManagement/v4/billingAccount",
    response_model=list[BillingAccount],
    tags=["Billing account"],
)
def list_billing_accounts(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="id"),
    q: str | None = Query(None, max_length=80),
):
    """Accounts in scope, with the open treatment. A read added for the copilot.

    `q` matches the account number, the customer number, or the customer name.
    The CSR console uses it as its search box.
    """
    stmt = _account_filter(session, principal, select(Account), Account.id, account_id)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        stmt = stmt.join(Customer, Customer.id == Account.customer_id).where(
            or_(
                Account.account_number.ilike(term, escape="\\"),
                Customer.customer_number.ilike(term, escape="\\"),
                Customer.given_name.ilike(term, escape="\\"),
                Customer.family_name.ilike(term, escape="\\"),
            )
        )
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(Account.account_number).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    views = []
    for account in rows:
        treatment, exemption = _open_treatment(session, account.id)
        customer = session.get(Customer, account.customer_id)
        views.append(to_billing_account(request, account, customer, treatment, exemption))
    return views


@router.get(
    "/accountManagement/v4/billingAccount/{account_id}",
    response_model=BillingAccount,
    tags=["Billing account"],
)
def get_billing_account(
    account_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    account = require_account(session, principal, account_id)
    treatment, exemption = _open_treatment(session, account.id)
    customer = session.get(Customer, account.customer_id)
    return to_billing_account(request, account, customer, treatment, exemption)


# --- Ops audit ------------------------------------------------------------


@audit_router.get("/ops/auditLog", response_model=list[AuditEntry], tags=["Audit"])
def list_audit(
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID | None = Query(None, alias="account.id"),
):
    del principal
    stmt = select(AuditLog)
    if account_id is not None:
        stmt = stmt.where(AuditLog.account_id == account_id)
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id).offset(offset).limit(limit)).all()
    _page_headers(response, total, len(rows))
    return [to_audit(row) for row in rows]
