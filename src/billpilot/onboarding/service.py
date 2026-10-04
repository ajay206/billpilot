"""Validate a new sale, then provision it. The first bill stays a preview."""

import re
import uuid

from sqlalchemy import select

from billpilot.api.security import Principal
from billpilot.models import Customer, Subscription
from billpilot.onboarding.provision import (
    ProvisionError,
    active_plan,
    credit_for_new_sale,
    provision,
    vas_products,
)

PHONE_RE = re.compile(r"^\+91\d{10}$")
MSISDN_RE = re.compile(r"^\d{10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def open_customer(session, principal: Principal, body) -> object:
    msisdn = body.msisdn.strip()
    phone = body.phone.strip()
    email = body.email.strip().lower()
    if not MSISDN_RE.match(msisdn):
        raise ProvisionError(422, "MSISDN must be 10 digits.")
    if not PHONE_RE.match(phone):
        raise ProvisionError(422, "Phone must be +91 followed by 10 digits.")
    if not EMAIL_RE.match(email):
        raise ProvisionError(422, "Email is not usable.")
    cycle_day = body.billingCycleDay
    if not 1 <= cycle_day <= 28:
        raise ProvisionError(422, "Billing cycle day must be from 1 to 28.")
    if session.scalar(select(Customer.id).where(Customer.email == email)) is not None:
        raise ProvisionError(409, "A customer with this email already exists.")
    if session.scalar(select(Subscription.id).where(Subscription.msisdn == msisdn)) is not None:
        raise ProvisionError(409, "A subscription with this MSISDN already exists.")
    plan = active_plan(session, body.planCode.strip())
    vas_rows = vas_products(list(body.optedInVas))
    credit_class, limit = credit_for_new_sale(plan.monthly_fee)
    suffix = uuid.uuid4().hex[:10].upper()
    return provision(
        session,
        given_name=body.givenName.strip(),
        family_name=body.familyName.strip(),
        email=email,
        phone=phone,
        city=body.city.strip(),
        state=body.state.strip(),
        plan=plan,
        msisdn=msisdn,
        vas_rows=vas_rows,
        credit_class=credit_class,
        credit_limit=limit,
        actor=principal.actor_id,
        customer_number=f"ONB-{suffix}",
        account_number=f"ACC-{suffix}",
        assigned_csr=principal.csr_code or "CSR-A",
        cycle_day=cycle_day,
        imsi=f"405{int(suffix, 16) % 10**12:012d}",
        sim_serial=f"{8991300000000000000 + (int(suffix, 16) % 10**6)}",
        opening_balance=None,
        bill_number=None,
    )
