"""Least-privilege account scope.

Customers see their own customer number. CSRs see accounts assigned to their code.
Ops can read across accounts. A known id outside that scope is 403, not an empty 200,
so a denial is explicit. A missing id is 404.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from billpilot.api.security import Principal
from billpilot.models import Account, Customer, Subscription


def visible_account_ids(session: Session, principal: Principal) -> set[uuid.UUID] | None:
    if principal.role == "ops":
        return None
    stmt = select(Account.id).join(Customer, Account.customer_id == Customer.id)
    if principal.role == "customer":
        stmt = stmt.where(Customer.customer_number == principal.customer_number)
    elif principal.role == "csr":
        stmt = stmt.where(Account.assigned_csr == principal.csr_code)
    else:
        raise HTTPException(status_code=403, detail="Unknown role.")
    return set(session.scalars(stmt))


def scope_accounts(stmt, column, session: Session, principal: Principal):
    allowed = visible_account_ids(session, principal)
    if allowed is None:
        return stmt
    if not allowed:
        return stmt.where(false())
    return stmt.where(column.in_(allowed))


def require_account(session: Session, principal: Principal, account_id: uuid.UUID) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    allowed = visible_account_ids(session, principal)
    if allowed is not None and account.id not in allowed:
        raise HTTPException(status_code=403, detail="This account is outside your role scope.")
    return account


def account_for_subscription(
    session: Session, principal: Principal, subscription_id: uuid.UUID
) -> tuple[Subscription, Account]:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    account = require_account(session, principal, subscription.account_id)
    return subscription, account
