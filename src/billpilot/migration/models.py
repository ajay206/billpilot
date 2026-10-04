"""Control rows for one migration batch. Billing rows are linked, not embedded."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from billpilot.models import Base


class MigrationBatch(Base):
    __tablename__ = "migration_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    batch_code: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    source_name: Mapped[str] = mapped_column(String(200))
    source_format: Mapped[str] = mapped_column(String(8))
    mapping_version: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dry_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_off_by: Mapped[str | None] = mapped_column(String(64))
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSONB)


class MigrationRecord(Base):
    __tablename__ = "migration_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migration_batches.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    source_key: Mapped[str] = mapped_column(String(96))
    record_kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(64))
    legacy_customer_id: Mapped[str | None] = mapped_column(String(64))
    legacy_plan: Mapped[str | None] = mapped_column(String(64))
    target_plan: Mapped[str | None] = mapped_column(String(32))
    msisdn: Mapped[str | None] = mapped_column(String(20))
    source_balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    payload: Mapped[dict] = mapped_column(JSONB)


class MigrationLink(Base):
    __tablename__ = "migration_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migration_batches.id"))
    source_key: Mapped[str] = mapped_column(String(96))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
