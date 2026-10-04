"""Credit profile set when a line is opened or migrated."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from billpilot.models import Base


class CreditProfile(Base):
    __tablename__ = "credit_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    credit_class: Mapped[str] = mapped_column(String(16))
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    set_by: Mapped[str] = mapped_column(String(64))
