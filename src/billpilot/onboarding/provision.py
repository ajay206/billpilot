"""Open one subscriber the same way for a new sale and for a migrated line.

The first bill of a new sale is a preview. A migrated balance is an opening
invoice, because that money is already owed. Entitlements, the collections
ladder, and the credit profile are written either way.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from billpilot.billing import ZERO, add_months, gst, money, quantity
from billpilot.models import (
    Account,
    AccountTreatment,
    Customer,
    Entitlement,
    EntitlementBalance,
    Invoice,
    InvoiceLine,
    Subscription,
    TariffPlan,
    TreatmentPlan,
    VasSubscription,
)
from billpilot.onboarding.models import CreditProfile
from billpilot.synthetic.catalog import CALLER_TUNE, DOMESTIC_FEATURES, OTT_MINI

KNOWN_VAS = {
    CALLER_TUNE["code"]: CALLER_TUNE,
    OTT_MINI["code"]: OTT_MINI,
}
CREDIT_MULTIPLE = Decimal("2")


class ProvisionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass
class Created:
    entity_type: str
    entity_id: uuid.UUID


@dataclass
class Provisioned:
    customer: Customer
    account: Account
    subscription: Subscription
    entitlements: list[Entitlement] = field(default_factory=list)
    balances: list[EntitlementBalance] = field(default_factory=list)
    vas: list[VasSubscription] = field(default_factory=list)
    treatment: AccountTreatment | None = None
    credit: CreditProfile | None = None
    invoice: Invoice | None = None
    preview: dict | None = None
    welcome: str = ""
    plan_code: str = ""
    plan_name: str = ""
    created: list[Created] = field(default_factory=list)

    def track(self, entity_type: str, entity_id: uuid.UUID) -> None:
        self.created.append(Created(entity_type, entity_id))


def standard_treatment(session: Session) -> TreatmentPlan:
    plan = session.scalar(select(TreatmentPlan).where(TreatmentPlan.code == "STANDARD"))
    if plan is None:
        raise ProvisionError(422, "The standard collections plan is not loaded.")
    return plan


def active_plan(session: Session, code: str) -> TariffPlan:
    plan = session.scalar(select(TariffPlan).where(TariffPlan.code == code))
    if plan is None:
        raise ProvisionError(422, f"Plan {code} does not exist.")
    if plan.lifecycle_status != "Active":
        raise ProvisionError(422, f"Plan {code} is not available for a new subscription.")
    return plan


def vas_products(codes: list[str]) -> list[dict]:
    chosen: list[dict] = []
    seen: set[str] = set()
    for code in codes:
        cleaned = code.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        product = KNOWN_VAS.get(cleaned)
        if product is None:
            known = ", ".join(sorted(KNOWN_VAS))
            raise ProvisionError(422, f"VAS {cleaned} is not in the catalogue ({known}). Only opted-in VAS are added.")
        chosen.append(product)
    return chosen


def credit_for_new_sale(monthly_fee: Decimal) -> tuple[str, Decimal]:
    return "new", money(monthly_fee * CREDIT_MULTIPLE)


def credit_for_migration(monthly_fee: Decimal, opening: Decimal) -> tuple[str, Decimal]:
    limit = money(monthly_fee * CREDIT_MULTIPLE)
    if opening > limit:
        return "watch", money(opening)
    return "standard", limit


def first_bill_preview(plan: TariffPlan, vas_rows: list[dict], today: date) -> dict:
    """A bill the customer can read before any invoice exists."""
    lines: list[dict] = []
    subtotal = ZERO
    fee = money(plan.monthly_fee)
    lines.append({"description": f"{plan.name} monthly fee", "chargeType": "recurring", "amount": f"{fee:.2f}"})
    subtotal += fee
    for product in vas_rows:
        amount = money(product["monthly_fee"])
        lines.append(
            {
                "description": f"{product['name']} (opted in)",
                "chargeType": "vas",
                "amount": f"{amount:.2f}",
            }
        )
        subtotal += amount
    subtotal = money(subtotal)
    tax = gst(subtotal)
    total = money(subtotal + tax)
    lines.append({"description": "GST 18%", "chargeType": "tax", "amount": f"{tax:.2f}"})
    due = today + timedelta(days=15)
    return {
        "currency": "INR",
        "periodStart": today.isoformat(),
        "periodEnd": add_months(today, 1).isoformat(),
        "dueDate": due.isoformat(),
        "subtotal": f"{subtotal:.2f}",
        "tax": f"{tax:.2f}",
        "total": f"{total:.2f}",
        "amountDue": f"{total:.2f}",
        "lines": lines,
        "posted": False,
    }


def welcome_message(given_name: str, plan_name: str, msisdn: str, preview: dict) -> str:
    return (
        f"Welcome, {given_name}. {plan_name} is active on {msisdn}. "
        f"Your first bill preview is {preview['total']} INR, due {preview['dueDate']}. "
        "This preview is not posted, so nothing is due until the first bill run."
    )


def _remember(result: Provisioned, entity_type: str, row) -> None:
    result.track(entity_type, row.id)


def provision(
    session: Session,
    *,
    given_name: str,
    family_name: str,
    email: str,
    phone: str,
    city: str,
    state: str,
    plan: TariffPlan,
    msisdn: str,
    vas_rows: list[dict],
    credit_class: str,
    credit_limit: Decimal,
    actor: str,
    customer_number: str,
    account_number: str,
    assigned_csr: str,
    cycle_day: int,
    imsi: str,
    sim_serial: str,
    opening_balance: Decimal | None,
    bill_number: str | None,
    now: datetime | None = None,
) -> Provisioned:
    """Insert the party and the products. The caller commits.

    `opening_balance` None means a new sale: no invoice. A decimal, including
    zero, is a migrated balance. Only a positive balance becomes an invoice.
    """
    moment = now or datetime.now(UTC)
    today = moment.date()
    treatment_plan = standard_treatment(session)
    result = Provisioned(
        customer=Customer(
            id=uuid.uuid4(),
            customer_number=customer_number,
            given_name=given_name,
            family_name=family_name,
            email=email,
            phone=phone,
            city=city,
            state=state,
            created_at=moment,
        ),
        account=Account(
            id=uuid.uuid4(),
            customer_id=uuid.UUID(int=0),
            account_number=account_number,
            status="active",
            currency="INR",
            billing_cycle_day=cycle_day,
            assigned_csr=assigned_csr,
            opened_at=moment,
            closed_at=None,
            created_at=moment,
        ),
        subscription=Subscription(
            id=uuid.uuid4(),
            account_id=uuid.UUID(int=0),
            tariff_plan_id=plan.id,
            msisdn=msisdn,
            imsi=imsi,
            sim_serial=sim_serial,
            status="active",
            discount_percent=ZERO,
            started_at=moment,
            ended_at=None,
            created_at=moment,
        ),
    )
    result.account.customer = result.customer
    result.subscription.account = result.account
    result.subscription.plan = plan
    session.add(result.customer)
    session.add(result.account)
    session.add(result.subscription)
    # Child rows have no relationship back to these parents. Flush the party
    # first so a later flush cannot insert treatment ahead of the account.
    session.flush()
    _remember(result, "customer", result.customer)
    _remember(result, "account", result.account)
    _remember(result, "subscription", result.subscription)

    period = (today, add_months(today, 1))
    for feature, unit, attr in DOMESTIC_FEATURES:
        allowance = quantity(Decimal(getattr(plan, attr)))
        entitlement = Entitlement(
            id=uuid.uuid4(),
            subscription_id=result.subscription.id,
            source_type="plan",
            source_ref=plan.code,
            feature_code=feature,
            allowance_quantity=allowance,
            unit=unit,
            status="active",
            valid_from=moment,
            valid_to=None,
            resets_on_bill_cycle=True,
            created_at=moment,
        )
        balance = EntitlementBalance(
            id=uuid.uuid4(),
            entitlement_id=entitlement.id,
            period_start=period[0],
            period_end=period[1],
            granted_quantity=allowance,
            consumed_quantity=quantity(ZERO),
            remaining_quantity=allowance,
            reset_at=moment,
        )
        session.add(entitlement)
        result.entitlements.append(entitlement)
        _remember(result, "entitlement", entitlement)
        session.flush()
        session.add(balance)
        result.balances.append(balance)
        _remember(result, "entitlement_balance", balance)

    for product in vas_rows:
        vas = VasSubscription(
            id=uuid.uuid4(),
            subscription_id=result.subscription.id,
            product_code=product["code"],
            name=product["name"],
            monthly_fee=money(product["monthly_fee"]),
            opted_in=True,
            status="active",
            started_at=moment,
            ended_at=None,
        )
        session.add(vas)
        result.vas.append(vas)
        _remember(result, "vas", vas)

    treatment = AccountTreatment(
        id=uuid.uuid4(),
        account_id=result.account.id,
        treatment_plan_id=treatment_plan.id,
        stage="none",
        status="active",
        started_at=moment,
        hold_reason=None,
        updated_at=moment,
    )
    credit = CreditProfile(
        id=uuid.uuid4(),
        account_id=result.account.id,
        credit_class=credit_class,
        credit_limit=money(credit_limit),
        currency="INR",
        set_at=moment,
        set_by=actor,
    )
    session.add(treatment)
    session.add(credit)
    session.flush()
    result.treatment = treatment
    result.credit = credit
    _remember(result, "treatment", treatment)
    _remember(result, "credit_profile", credit)

    if opening_balance is not None and opening_balance > 0:
        if not bill_number:
            raise ProvisionError(422, "An opening balance needs a bill number.")
        amount = money(opening_balance)
        invoice = Invoice(
            id=uuid.uuid4(),
            account_id=result.account.id,
            bill_number=bill_number,
            period_start=add_months(today, -1),
            period_end=today,
            issue_date=today,
            due_date=today,
            status="issued",
            subtotal=amount,
            tax=ZERO,
            total=amount,
            amount_due=amount,
            currency="INR",
            created_at=moment,
        )
        line = InvoiceLine(
            id=uuid.uuid4(),
            invoice_id=invoice.id,
            line_number=1,
            charge_type="adjustment",
            description="Opening balance migrated from the legacy ledger.",
            quantity=Decimal("1.000"),
            unit_price=amount,
            amount=amount,
            subscription_id=result.subscription.id,
            usage_event_id=None,
            tariff_plan_id=plan.id,
        )
        line.invoice = invoice
        session.add(invoice)
        session.add(line)
        session.flush()
        result.invoice = invoice
        _remember(result, "invoice", invoice)
        _remember(result, "invoice_line", line)

    preview = first_bill_preview(plan, vas_rows, today)
    result.preview = preview
    result.plan_code = plan.code
    result.plan_name = plan.name
    result.welcome = welcome_message(given_name, plan.name, msisdn, preview)
    return result
