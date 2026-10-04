"""ORM mapping for the 23 billing tables.

The SQL migration is the source of truth for constraints and indexes. These
classes exist so the API and the generator can talk to those tables by name.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    customer_number: Mapped[str] = mapped_column(String(32))
    given_name: Mapped[str] = mapped_column(String(80))
    family_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    accounts: Mapped[list["Account"]] = relationship(back_populates="customer")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    account_number: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    billing_cycle_day: Mapped[int] = mapped_column(Integer)
    assigned_csr: Mapped[str] = mapped_column(String(32))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="accounts")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="account")


class TariffPlan(Base):
    __tablename__ = "tariff_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    monthly_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    included_voice_minutes: Mapped[int] = mapped_column(Integer)
    included_data_mb: Mapped[int] = mapped_column(Integer)
    included_sms: Mapped[int] = mapped_column(Integer)
    voice_overage_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    data_overage_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    sms_overage_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    roaming_voice_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    roaming_data_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    roaming_sms_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    lifecycle_status: Mapped[str] = mapped_column(String(16))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    tariff_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tariff_plans.id"))
    msisdn: Mapped[str] = mapped_column(String(15))
    imsi: Mapped[str] = mapped_column(String(20))
    sim_serial: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    account: Mapped[Account] = relationship(back_populates="subscriptions")
    plan: Mapped[TariffPlan] = relationship()


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"))
    event_type: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16))
    rate_applied: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    rated_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    roaming_country: Mapped[str | None] = mapped_column(String(40))
    destination: Mapped[str | None] = mapped_column(String(80))
    billed: Mapped[bool] = mapped_column(Boolean)
    rating_status: Mapped[str] = mapped_column(String(16))
    source_event_id: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    bill_number: Mapped[str] = mapped_column(String(32))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"))
    line_number: Mapped[int] = mapped_column(Integer)
    charge_type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"))
    usage_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usage_events.id"))
    tariff_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tariff_plans.id"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    payment_number: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16))
    reference: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16))
    failure_reason: Mapped[str | None] = mapped_column(String(80))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    ticket_number: Mapped[str] = mapped_column(String(32))
    ticket_type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    opened_by: Mapped[str] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id"))
    status: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    opened_by: Mapped[str] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Adjustment(Base):
    __tablename__ = "adjustments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    invoice_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice_lines.id"))
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("disputes.id"))
    adjustment_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    proposed_by: Mapped[str] = mapped_column(String(64))
    decided_by: Mapped[str | None] = mapped_column(String(64))
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)


class VasSubscription(Base):
    __tablename__ = "vas_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"))
    product_code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80))
    monthly_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    opted_in: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RoamingPack(Base):
    __tablename__ = "roaming_packs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"))
    pack_code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80))
    zone: Mapped[str] = mapped_column(String(40))
    data_mb: Mapped[int] = mapped_column(Integer)
    voice_minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))


class Entitlement(Base):
    __tablename__ = "entitlements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"))
    source_type: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(String(80))
    feature_code: Mapped[str] = mapped_column(String(32))
    allowance_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resets_on_bill_cycle: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EntitlementBalance(Base):
    __tablename__ = "entitlement_balances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    entitlement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entitlements.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    granted_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    consumed_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TreatmentPlan(Base):
    __tablename__ = "treatment_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    reminder_after_days: Mapped[int] = mapped_column(Integer)
    soft_bar_after_days: Mapped[int] = mapped_column(Integer)
    hard_bar_after_days: Mapped[int] = mapped_column(Integer)
    disconnect_after_days: Mapped[int] = mapped_column(Integer)


class AccountTreatment(Base):
    __tablename__ = "account_treatment"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    treatment_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("treatment_plans.id"))
    stage: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hold_reason: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TreatmentExemption(Base):
    __tablename__ = "treatment_exemptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64))


class DunningEvent(Base):
    __tablename__ = "dunning_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    account_treatment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account_treatment.id"))
    event_type: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    promise_pay_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promise_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class FraudFlag(Base):
    __tablename__ = "fraud_flags"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"))
    flag_type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict] = mapped_column(JSONB)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    incident_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    related_entity_type: Mapped[str | None] = mapped_column(String(40))
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_role: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    request_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict] = mapped_column(JSONB)


class KnowledgeChunk(Base):
    """One section of the synthetic policy corpus, with its embedding."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    section: Mapped[str] = mapped_column(String(200))
    source_path: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    # 256 matches the hash embedder and the API embedder's dimensions argument.
    embedding: Mapped[list] = mapped_column(Vector(256))


class AgentRun(Base):
    """One copilot turn. The transcript lives here; audit_log points at the same request."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64))
    persona: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_message: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    refusal: Mapped[bool] = mapped_column(Boolean)
    grounded: Mapped[bool] = mapped_column(Boolean)
    tool_calls: Mapped[list] = mapped_column(JSONB)
    citations: Mapped[list] = mapped_column(JSONB)
    proposed_actions: Mapped[list] = mapped_column(JSONB)
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    latency_ms: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(80))
    audit_log_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit_log.id"))
    # Langfuse trace id for this turn. Null when tracing is off.
    trace_id: Mapped[str | None] = mapped_column(String(64))
