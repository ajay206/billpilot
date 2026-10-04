"""Synthetic demo users. Passwords are for the portfolio demo only.

They are not credentials for any real system. The login page lists them so a
reviewer can sign in. Re-seeding the ledger does not delete these rows; a boot
against an existing database inserts any username that is missing.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billpilot.auth.passwords import hash_password
from billpilot.models import Customer, User

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "billpilot.demo.users")


@dataclass(frozen=True)
class DemoUser:
    username: str
    display_name: str
    password: str
    role: str
    customer_number: str | None
    csr_code: str | None
    scope: str

    @property
    def id(self) -> uuid.UUID:
        return uuid.uuid5(_NAMESPACE, self.username)


# Even customer indexes are assigned to CSR-A (index % 2 == 0). CUST-000001 is index 0.
DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser(
        "priya.sharma",
        "Priya Sharma",
        "demo-priya",
        "customer",
        "CUST-000001",
        None,
        "CUST-000001 only",
    ),
    DemoUser(
        "arjun.mehta",
        "Arjun Mehta",
        "demo-arjun",
        "customer",
        "CUST-000003",
        None,
        "CUST-000003 only",
    ),
    DemoUser(
        "neha.iyer",
        "Neha Iyer",
        "demo-neha",
        "customer",
        "CUST-000005",
        None,
        "CUST-000005 only",
    ),
    DemoUser(
        "ananya.rao",
        "Ananya Rao",
        "demo-ananya",
        "csr",
        None,
        "CSR-A",
        "Accounts assigned to CSR-A",
    ),
    DemoUser(
        "vikram.nair",
        "Vikram Nair",
        "demo-vikram",
        "csr",
        None,
        "CSR-B",
        "Accounts assigned to CSR-B",
    ),
    DemoUser(
        "meera.kapoor",
        "Meera Kapoor",
        "demo-meera",
        "ops",
        None,
        None,
        "All accounts, approvals, and audit",
    ),
)


def holder_name_for_index(index: int) -> tuple[str, str] | None:
    """Given and family name for a seeded customer who also has a demo login.

    Index 0 is CUST-000001. The generator still draws a Faker name for that
    index, then replaces it, so later customers keep the same sequence.
    """
    number = f"CUST-{index + 1:06d}"
    for spec in DEMO_USERS:
        if spec.role == "customer" and spec.customer_number == number:
            given, _, family = spec.display_name.partition(" ")
            return given, family
    return None


def align_demo_holders(session: Session) -> int:
    """Point the demo customer rows at the sign-in names. Safe to run again.

    An existing database already has Faker names. Boot updates only the three
    demo holders and leaves every other customer alone.
    """
    updated = 0
    for spec in DEMO_USERS:
        if spec.role != "customer" or not spec.customer_number:
            continue
        given, _, family = spec.display_name.partition(" ")
        customer = session.scalar(select(Customer).where(Customer.customer_number == spec.customer_number))
        if customer is None or (customer.given_name == given and customer.family_name == family):
            continue
        customer.given_name = given
        customer.family_name = family
        updated += 1
    return updated


def ensure_demo_users(session: Session) -> int:
    """Insert any demo user that is not already there, and align holder names.

    Billing rows other than those three names are left as they are. Password
    hashes of existing users are not reset.
    """
    present = set(session.scalars(select(User.username)))
    inserted = 0
    now = datetime.now(UTC)
    for spec in DEMO_USERS:
        if spec.username in present:
            continue
        session.add(
            User(
                id=spec.id,
                username=spec.username,
                display_name=spec.display_name,
                password_hash=hash_password(spec.password),
                role=spec.role,
                customer_number=spec.customer_number,
                csr_code=spec.csr_code,
                created_at=now,
            )
        )
        inserted += 1
    renamed = align_demo_holders(session)
    if inserted or renamed:
        session.commit()
    return inserted
