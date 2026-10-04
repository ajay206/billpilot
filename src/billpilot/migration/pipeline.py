"""Load, dry-run, sign off, commit, and roll back one migration batch.

Dry run and sign-off write the control tables only. Commit writes the billing
ledger in the caller's transaction. A second commit of the same batch inserts
nothing. Rollback deletes only the rows this batch created.
"""

import csv
import io
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from billpilot.billing import ZERO, money
from billpilot.migration.legacy import FIELDS, parse_balance
from billpilot.migration.mapping import PlanMap, load_plan_map
from billpilot.migration.models import MigrationBatch, MigrationLink, MigrationRecord
from billpilot.models import Customer, Invoice, Subscription, TariffPlan
from billpilot.onboarding.provision import (
    KNOWN_VAS,
    credit_for_migration,
    provision,
    vas_products,
)
from billpilot.onboarding.provision import (
    active_plan as lookup_plan,
)

MSISDN_RE = re.compile(r"^\d{10}$")
PHONE_RE = re.compile(r"^\+91\d{10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TARGET_STATUSES = frozenset({"ready", "migrated"})

# Rollback deletes children before parents. Names are fixed, not taken from the file.
_DELETE_ORDER = (
    ("invoice_line", "invoice_lines"),
    ("invoice", "invoices"),
    ("entitlement_balance", "entitlement_balances"),
    ("entitlement", "entitlements"),
    ("vas", "vas_subscriptions"),
    ("treatment", "account_treatment"),
    ("credit_profile", "credit_profiles"),
    ("subscription", "subscriptions"),
    ("account", "accounts"),
    ("customer", "customers"),
)


class MigrationError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass
class Outcome:
    ordinal: int
    source_key: str
    record_kind: str
    status: str
    reason: str | None
    legacy_customer_id: str | None
    legacy_plan: str | None
    target_plan: str | None
    msisdn: str | None
    source_balance: Decimal | None
    payload: dict


def analyse(session: Session, records: list[dict]) -> list[Outcome]:
    """Classify every source row. Nothing in the billing ledger is written."""
    plan_map = load_plan_map()
    catalogue = set(session.scalars(select(TariffPlan.code).where(TariffPlan.lifecycle_status == "Active")))
    ledger_msisdn = set(session.scalars(select(Subscription.msisdn)))
    ledger_email = {email.lower() for email in session.scalars(select(Customer.email))}
    outcomes: list[Outcome] = []
    customers: dict[str, Outcome] = {}
    seen_customer: set[str] = set()
    seen_email: set[str] = set()
    services_for: dict[str, list[Outcome]] = defaultdict(list)
    balances_for: dict[str, list[Outcome]] = defaultdict(list)
    seen_msisdn: set[str] = set()
    seen_balance: set[str] = set()
    file_customer_ids = {
        row["legacy_customer_id"]
        for row in records
        if row.get("record_type") == "customer" and row.get("legacy_customer_id")
    }

    def add(outcome: Outcome) -> Outcome:
        outcomes.append(outcome)
        return outcome

    for raw in records:
        if raw.get("record_type") != "customer":
            continue
        outcome = add(_customer_outcome(raw, seen_customer, seen_email, ledger_email))
        if outcome.status == "ready" and outcome.legacy_customer_id:
            customers[outcome.legacy_customer_id] = outcome

    for raw in records:
        if raw.get("record_type") != "service":
            continue
        outcome = add(
            _service_outcome(raw, customers, file_customer_ids, seen_msisdn, ledger_msisdn, plan_map, catalogue)
        )
        if outcome.legacy_customer_id:
            services_for[outcome.legacy_customer_id].append(outcome)

    for rows in services_for.values():
        ready = [row for row in rows if row.status == "ready"]
        for extra in ready[1:]:
            extra.status = "rejected"
            extra.reason = "duplicate_service"

    for raw in records:
        if raw.get("record_type") != "balance":
            continue
        outcome = add(_balance_outcome(raw, customers, file_customer_ids, seen_balance))
        if outcome.legacy_customer_id:
            balances_for[outcome.legacy_customer_id].append(outcome)

    for raw in records:
        if raw.get("record_type") not in {"customer", "service", "balance"}:
            ordinal = int(raw.get("ordinal") or 0)
            raise MigrationError(422, f"Record {ordinal + 1} has an unknown record_type.")

    for legacy_id, customer in customers.items():
        reason = _block_reason(legacy_id, services_for, balances_for)
        if reason is None:
            continue
        customer.status = "skipped"
        customer.reason = reason
        for outcome in services_for.get(legacy_id, []):
            if outcome.status == "ready":
                outcome.status = "skipped"
                outcome.reason = reason
        for outcome in balances_for.get(legacy_id, []):
            if outcome.status == "ready":
                outcome.status = "skipped"
                outcome.reason = reason

    outcomes.sort(key=lambda item: item.ordinal)
    return outcomes


def summarize(outcomes: list[Outcome], plan_map: PlanMap | None = None) -> dict:
    plan_map = plan_map or load_plan_map()
    balance_rows = [row for row in outcomes if row.record_kind == "balance" and row.source_balance is not None]
    raw_total = money(sum((row.source_balance for row in balance_rows), ZERO))
    accepted_rows = [row for row in balance_rows if row.status in TARGET_STATUSES]
    accepted = money(sum((row.source_balance for row in accepted_rows), ZERO))
    by_reason: dict[str, int] = {}
    for row in outcomes:
        if row.status == "rejected" and row.reason:
            by_reason[row.reason] = by_reason.get(row.reason, 0) + 1
    suggestions = _suggestions(outcomes, plan_map)
    return {
        "source": {
            "records": len(outcomes),
            "customers": _count(outcomes, "customer"),
            "services": _count(outcomes, "service"),
            "balances": _count(outcomes, "balance"),
            "balanceTotal": f"{raw_total:.2f}",
        },
        "target": {
            "customers": _count(outcomes, "customer", TARGET_STATUSES),
            "services": _count(outcomes, "service", TARGET_STATUSES),
            "balances": _count(outcomes, "balance", TARGET_STATUSES),
            "balanceTotal": f"{accepted:.2f}",
        },
        "acceptedBalanceTotal": f"{accepted:.2f}",
        "balanceMatched": True,
        "rejected": sum(1 for row in outcomes if row.status == "rejected"),
        "skipped": sum(1 for row in outcomes if row.status == "skipped"),
        "migrated": sum(1 for row in outcomes if row.status == "migrated"),
        "byReason": by_reason,
        "mappingSuggestions": suggestions,
        "mappingVersion": plan_map.version,
        "writes": 0,
    }


def load_batch(
    session: Session,
    *,
    records: list[dict],
    source_name: str,
    source_format: str,
    actor: str,
) -> MigrationBatch:
    outcomes = analyse(session, records)
    plan_map = load_plan_map()
    now = datetime.now(UTC)
    batch = MigrationBatch(
        id=uuid.uuid4(),
        batch_code="MIG-" + uuid.uuid4().hex[:8].upper(),
        status="loaded",
        source_name=source_name[:200],
        source_format=source_format,
        mapping_version=plan_map.version,
        created_by=actor,
        created_at=now,
        dry_run_at=None,
        signed_off_by=None,
        signed_off_at=None,
        committed_at=None,
        rolled_back_at=None,
        summary=summarize(outcomes, plan_map),
    )
    session.add(batch)
    session.flush()
    _insert_outcomes(session, batch.id, outcomes)
    return batch


def dry_run(session: Session, batch_id: uuid.UUID) -> MigrationBatch:
    """Re-check the stored file against the live ledger. Billing tables stay untouched."""
    batch = require_batch(session, batch_id)
    if batch.status == "committed":
        return batch
    raws = [_stored_raw(record) for record in _records(session, batch.id)]
    outcomes = analyse(session, raws)
    session.execute(delete(MigrationRecord).where(MigrationRecord.batch_id == batch.id))
    _insert_outcomes(session, batch.id, outcomes)
    summary = summarize(outcomes, load_plan_map())
    summary["writes"] = 0
    batch.summary = summary
    batch.status = "dry_run"
    batch.dry_run_at = datetime.now(UTC)
    batch.signed_off_by = None
    batch.signed_off_at = None
    return batch


def sign_off(session: Session, batch_id: uuid.UUID, actor: str) -> MigrationBatch:
    batch = require_batch(session, batch_id)
    if batch.status != "dry_run":
        raise MigrationError(409, "Dry-run the batch before signing off the mapping.")
    now = datetime.now(UTC)
    batch.status = "signed_off"
    batch.signed_off_by = actor
    batch.signed_off_at = now
    summary = dict(batch.summary)
    summary["signedOffBy"] = actor
    summary["writes"] = 0
    batch.summary = summary
    return batch


def commit_batch(session: Session, batch_id: uuid.UUID, actor: str) -> dict:
    """Insert ready groups. The caller commits this session, or rolls it back."""
    batch = require_batch(session, batch_id)
    if batch.status == "committed":
        summary = dict(batch.summary)
        summary["idempotent"] = True
        summary["writes"] = 0
        batch.summary = summary
        return summary
    if batch.status != "signed_off":
        raise MigrationError(409, "Sign off the mapping after a dry run before committing this batch.")
    records = _records(session, batch.id)
    groups = _groups(records)
    accepted = money(
        sum(
            (
                row.source_balance
                for row in records
                if row.record_kind == "balance" and row.status == "ready" and row.source_balance is not None
            ),
            ZERO,
        )
    )
    token = batch.batch_code.split("-", 1)[-1]
    invoice_ids: list[uuid.UUID] = []
    link_rows: list[tuple[str, str, uuid.UUID]] = []
    for index, group in enumerate(groups, start=1):
        created, invoice_id = insert_group(session, group, index=index, token=token, actor=actor)
        link_rows.extend(created)
        if invoice_id is not None:
            invoice_ids.append(invoice_id)
    session.flush()
    actual = _posted_balance(session, invoice_ids)
    if actual != accepted:
        raise MigrationError(409, "Opening balances do not match the accepted source total. Nothing was committed.")
    for record in records:
        if record.status == "ready":
            record.status = "migrated"
    summary = summarize(_outcomes_from(records), load_plan_map())
    summary["target"]["balanceTotal"] = f"{actual:.2f}"
    summary["acceptedBalanceTotal"] = f"{accepted:.2f}"
    summary["balanceMatched"] = True
    summary["idempotent"] = False
    summary["writes"] = len(groups)
    summary["signedOffBy"] = batch.signed_off_by
    batch.summary = summary
    batch.status = "committed"
    batch.committed_at = datetime.now(UTC)
    for source_key, entity_type, entity_id in link_rows:
        session.add(
            MigrationLink(
                id=uuid.uuid4(),
                batch_id=batch.id,
                source_key=source_key,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
    return summary


def insert_group(session: Session, group: dict, *, index: int, token: str, actor: str):
    """Create one migrated subscriber. Tests replace this to prove the batch is one transaction."""
    customer = group["customer"]
    service = group["service"]
    balance = group["balance"]
    payload = customer.payload
    plan = lookup_plan(session, service.target_plan or "")
    vas_code = str(service.payload.get("vas_opt_in") or "").upper()
    vas_rows = vas_products([vas_code] if vas_code else [])
    opening = ZERO if balance is None or balance.source_balance is None else money(balance.source_balance)
    credit_class, limit = credit_for_migration(plan.monthly_fee, opening)
    suffix = f"{token}-{index:04d}"
    result = provision(
        session,
        given_name=payload["given_name"],
        family_name=payload["family_name"],
        email=payload["email"].lower(),
        phone=payload["phone"],
        city=payload["city"],
        state=payload["state"],
        plan=plan,
        msisdn=service.msisdn or "",
        vas_rows=vas_rows,
        credit_class=credit_class,
        credit_limit=limit,
        actor=actor,
        customer_number=f"MIG-{suffix}",
        account_number=f"ACC-{suffix}",
        assigned_csr="CSR-A" if index % 2 == 0 else "CSR-B",
        cycle_day=1,
        imsi=f"404{index:012d}",
        sim_serial=f"{8991200000000000000 + index}",
        opening_balance=opening,
        bill_number=f"MB-{suffix}" if opening > 0 else None,
    )
    created = [(customer.source_key, item.entity_type, item.entity_id) for item in result.created]
    invoice_id = None if result.invoice is None else result.invoice.id
    return created, invoice_id


def rollback_batch(session: Session, batch_id: uuid.UUID) -> dict:
    batch = require_batch(session, batch_id)
    if batch.status == "rolled_back":
        summary = dict(batch.summary)
        summary["alreadyRolledBack"] = True
        summary["restored"] = True
        summary["writes"] = 0
        batch.summary = summary
        return summary
    if batch.status != "committed":
        raise MigrationError(409, "Only a committed batch can be rolled back.")
    links = list(session.scalars(select(MigrationLink).where(MigrationLink.batch_id == batch.id)))
    by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
    for link in links:
        by_type[link.entity_type].append(link.entity_id)
    for entity_type, table in _DELETE_ORDER:
        for entity_id in by_type.get(entity_type, []):
            session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": entity_id})
    session.execute(delete(MigrationLink).where(MigrationLink.batch_id == batch.id))
    records = _records(session, batch.id)
    for record in records:
        if record.status == "migrated":
            record.status = "ready"
    summary = dict(batch.summary)
    summary["restored"] = True
    summary["alreadyRolledBack"] = False
    summary["writes"] = 0
    summary["migrated"] = 0
    batch.summary = summary
    batch.status = "rolled_back"
    batch.rolled_back_at = datetime.now(UTC)
    return summary


def require_batch(session: Session, batch_id: uuid.UUID) -> MigrationBatch:
    batch = session.get(MigrationBatch, batch_id)
    if batch is None:
        raise MigrationError(404, "Migration batch not found.")
    return batch


def list_batches(session: Session, *, offset: int, limit: int) -> tuple[list[MigrationBatch], int]:
    total = session.scalar(select(func.count()).select_from(MigrationBatch)) or 0
    rows = list(
        session.scalars(select(MigrationBatch).order_by(MigrationBatch.created_at.desc()).offset(offset).limit(limit))
    )
    return rows, int(total)


def batch_records(session: Session, batch_id: uuid.UUID) -> list[MigrationRecord]:
    return _records(session, batch_id)


def latest_batch(session: Session) -> MigrationBatch | None:
    return session.scalar(select(MigrationBatch).order_by(MigrationBatch.created_at.desc()).limit(1))


def reconciliation_csv(batch: MigrationBatch, records: list[MigrationRecord]) -> str:
    summary = batch.summary or {}
    source = summary.get("source") or {}
    target = summary.get("target") or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "section",
            "key",
            "kind",
            "status",
            "reason",
            "legacy_plan",
            "target_plan",
            "msisdn",
            "source_balance",
            "target_balance",
        ]
    )
    writer.writerow(
        [
            "summary",
            "records",
            "count",
            source.get("records", ""),
            "",
            "",
            "",
            "",
            source.get("balanceTotal", ""),
            target.get("balanceTotal", ""),
        ]
    )
    writer.writerow(
        [
            "summary",
            "balance_matched",
            "flag",
            summary.get("balanceMatched", ""),
            "",
            "",
            "",
            "",
            summary.get("acceptedBalanceTotal", ""),
            target.get("balanceTotal", ""),
        ]
    )
    writer.writerow(
        [
            "summary",
            "rejected",
            "count",
            summary.get("rejected", ""),
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    for reason, count in sorted((summary.get("byReason") or {}).items()):
        writer.writerow(["summary", "reject", reason, count, reason, "", "", "", "", ""])
    for record in records:
        source_balance = "" if record.source_balance is None else f"{record.source_balance:.2f}"
        target_balance = ""
        if record.record_kind == "balance" and record.status in TARGET_STATUSES and record.source_balance is not None:
            target_balance = f"{record.source_balance:.2f}"
        writer.writerow(
            [
                "record",
                record.source_key,
                record.record_kind,
                record.status,
                record.reason or "",
                record.legacy_plan or "",
                record.target_plan or "",
                record.msisdn or "",
                source_balance,
                target_balance,
            ]
        )
    return buffer.getvalue()


def record_dict(record: MigrationRecord) -> dict:
    return {
        "id": str(record.id),
        "ordinal": record.ordinal,
        "sourceKey": record.source_key,
        "recordKind": record.record_kind,
        "status": record.status,
        "reason": record.reason,
        "legacyCustomerId": record.legacy_customer_id,
        "legacyPlan": record.legacy_plan,
        "targetPlan": record.target_plan,
        "msisdn": record.msisdn,
        "sourceBalance": None if record.source_balance is None else f"{record.source_balance:.2f}",
    }


def rejects_for(records: list[MigrationRecord], batch: MigrationBatch) -> dict:
    rejected = [record for record in records if record.status == "rejected"]
    by_reason: dict[str, int] = {}
    for record in rejected:
        if record.reason:
            by_reason[record.reason] = by_reason.get(record.reason, 0) + 1
    return {
        "batchId": str(batch.id),
        "batchCode": batch.batch_code,
        "status": batch.status,
        "rejects": [record_dict(record) for record in rejected],
        "byReason": by_reason,
    }


def _records(session: Session, batch_id: uuid.UUID) -> list[MigrationRecord]:
    return list(
        session.scalars(
            select(MigrationRecord).where(MigrationRecord.batch_id == batch_id).order_by(MigrationRecord.ordinal)
        )
    )


def _groups(records: list[MigrationRecord]) -> list[dict]:
    grouped: dict[str, list[MigrationRecord]] = defaultdict(list)
    for record in records:
        if record.status == "ready" and record.legacy_customer_id:
            grouped[record.legacy_customer_id].append(record)
    groups = []
    for legacy_id in sorted(grouped, key=lambda key: min(row.ordinal for row in grouped[key])):
        rows = grouped[legacy_id]
        customer = next((row for row in rows if row.record_kind == "customer"), None)
        service = next((row for row in rows if row.record_kind == "service"), None)
        balance = next((row for row in rows if row.record_kind == "balance"), None)
        if customer is None or service is None:
            continue
        groups.append({"legacy_id": legacy_id, "customer": customer, "service": service, "balance": balance})
    return groups


def _insert_outcomes(session: Session, batch_id: uuid.UUID, outcomes: list[Outcome]) -> None:
    for outcome in outcomes:
        session.add(
            MigrationRecord(
                id=uuid.uuid4(),
                batch_id=batch_id,
                ordinal=outcome.ordinal,
                source_key=outcome.source_key,
                record_kind=outcome.record_kind,
                status=outcome.status,
                reason=outcome.reason,
                legacy_customer_id=outcome.legacy_customer_id,
                legacy_plan=outcome.legacy_plan,
                target_plan=outcome.target_plan,
                msisdn=outcome.msisdn,
                source_balance=outcome.source_balance,
                payload=outcome.payload,
            )
        )


def _stored_raw(record: MigrationRecord) -> dict:
    raw = dict(record.payload)
    raw["ordinal"] = str(record.ordinal)
    raw.setdefault("record_type", record.record_kind)
    return raw


def _outcomes_from(records: list[MigrationRecord]) -> list[Outcome]:
    return [
        Outcome(
            ordinal=record.ordinal,
            source_key=record.source_key,
            record_kind=record.record_kind,
            status=record.status,
            reason=record.reason,
            legacy_customer_id=record.legacy_customer_id,
            legacy_plan=record.legacy_plan,
            target_plan=record.target_plan,
            msisdn=record.msisdn,
            source_balance=record.source_balance,
            payload=record.payload,
        )
        for record in records
    ]


def _posted_balance(session: Session, invoice_ids: list[uuid.UUID]) -> Decimal:
    if not invoice_ids:
        return ZERO
    total = session.scalar(select(func.coalesce(func.sum(Invoice.amount_due), 0)).where(Invoice.id.in_(invoice_ids)))
    return money(Decimal(total))


def _count(outcomes: list[Outcome], kind: str, statuses: frozenset[str] | None = None) -> int:
    return sum(1 for row in outcomes if row.record_kind == kind and (statuses is None or row.status in statuses))


def _suggestions(outcomes: list[Outcome], plan_map: PlanMap) -> list[dict]:
    seen: list[str] = []
    suggestions = []
    for row in outcomes:
        if row.record_kind != "service" or not row.legacy_plan or row.legacy_plan in seen:
            continue
        seen.append(row.legacy_plan)
        rule = plan_map.suggest(row.legacy_plan)
        suggestions.append(
            {
                "legacyCode": row.legacy_plan,
                "legacyName": None if rule is None else rule.legacy_name,
                "targetCode": None if rule is None else rule.target_code,
                "rationale": (rule.rationale if rule is not None else "No mapping rule matches this legacy plan code."),
                "recordCount": sum(1 for item in outcomes if item.legacy_plan == row.legacy_plan),
            }
        )
    return suggestions


def _payload(raw: dict) -> dict:
    payload = {key: str(raw.get(key) or "") for key in FIELDS}
    payload["ordinal"] = str(raw.get("ordinal") or "0")
    return payload


def _customer_outcome(raw: dict, seen_customer: set[str], seen_email: set[str], ledger_email: set[str]) -> Outcome:
    ordinal = int(raw.get("ordinal") or 0)
    legacy_id = raw.get("legacy_customer_id") or ""
    email = (raw.get("email") or "").lower()
    status = "ready"
    reason = None
    required = (legacy_id, raw.get("given_name"), raw.get("family_name"), raw.get("city"), raw.get("state"))
    if not all(required):
        status, reason = "rejected", "incomplete_customer"
    elif legacy_id in seen_customer:
        status, reason = "rejected", "duplicate_customer"
    elif not PHONE_RE.match(raw.get("phone") or ""):
        status, reason = "rejected", "bad_phone"
    elif not EMAIL_RE.match(email):
        status, reason = "rejected", "bad_email"
    elif email in ledger_email or email in seen_email:
        status, reason = "rejected", "duplicate_email"
    if status == "ready":
        seen_customer.add(legacy_id)
        seen_email.add(email)
    return Outcome(
        ordinal=ordinal,
        source_key=f"customer:{legacy_id or 'blank'}:{ordinal}",
        record_kind="customer",
        status=status,
        reason=reason,
        legacy_customer_id=legacy_id or None,
        legacy_plan=None,
        target_plan=None,
        msisdn=None,
        source_balance=None,
        payload=_payload(raw),
    )


def _service_outcome(
    raw: dict,
    customers: dict[str, Outcome],
    file_customer_ids: set[str],
    seen_msisdn: set[str],
    ledger_msisdn: set[str],
    plan_map: PlanMap,
    catalogue: set[str],
) -> Outcome:
    ordinal = int(raw.get("ordinal") or 0)
    legacy_id = raw.get("legacy_customer_id") or ""
    msisdn = raw.get("msisdn") or ""
    legacy_plan = (raw.get("legacy_plan") or "").upper()
    rule = plan_map.suggest(legacy_plan) if legacy_plan else None
    target = rule.target_code if rule is not None and rule.target_code in catalogue else None
    vas = (raw.get("vas_opt_in") or "").upper()
    status = "ready"
    reason = None
    if not legacy_id or legacy_id not in file_customer_ids:
        status, reason = "rejected", "orphan_service"
    elif legacy_id not in customers:
        status, reason = "rejected", "customer_rejected"
    elif not MSISDN_RE.match(msisdn):
        status, reason = "rejected", "bad_msisdn"
    elif msisdn in seen_msisdn or msisdn in ledger_msisdn:
        status, reason = "rejected", "duplicate_msisdn"
    elif target is None:
        status, reason = "rejected", "unknown_plan"
    elif vas and vas not in KNOWN_VAS:
        status, reason = "rejected", "unknown_vas"
    if status == "ready":
        seen_msisdn.add(msisdn)
    return Outcome(
        ordinal=ordinal,
        source_key=f"service:{legacy_id or 'blank'}:{ordinal}",
        record_kind="service",
        status=status,
        reason=reason,
        legacy_customer_id=legacy_id or None,
        legacy_plan=legacy_plan or None,
        target_plan=target,
        msisdn=msisdn or None,
        source_balance=None,
        payload=_payload(raw),
    )


def _balance_outcome(
    raw: dict,
    customers: dict[str, Outcome],
    file_customer_ids: set[str],
    seen_balance: set[str],
) -> Outcome:
    ordinal = int(raw.get("ordinal") or 0)
    legacy_id = raw.get("legacy_customer_id") or ""
    status = "ready"
    reason = None
    amount: Decimal | None
    try:
        parsed = parse_balance(raw.get("balance") or "")
        invalid = False
    except ValueError:
        parsed = None
        invalid = True
    if not legacy_id or legacy_id not in file_customer_ids:
        status, reason = "rejected", "orphan_balance"
    elif legacy_id not in customers:
        status, reason = "rejected", "customer_rejected"
    elif invalid or parsed is None:
        status, reason = "rejected", "invalid_balance"
    elif parsed < 0:
        status, reason = "rejected", "negative_balance"
    elif legacy_id in seen_balance:
        status, reason = "rejected", "duplicate_balance"
    if status == "ready" and parsed is not None:
        seen_balance.add(legacy_id)
        amount = money(parsed)
    elif parsed is not None and not invalid:
        amount = money(parsed)
    else:
        amount = None
    return Outcome(
        ordinal=ordinal,
        source_key=f"balance:{legacy_id or 'blank'}:{ordinal}",
        record_kind="balance",
        status=status,
        reason=reason,
        legacy_customer_id=legacy_id or None,
        legacy_plan=None,
        target_plan=None,
        msisdn=None,
        source_balance=amount,
        payload=_payload(raw),
    )


def _block_reason(
    legacy_id: str,
    services_for: dict[str, list[Outcome]],
    balances_for: dict[str, list[Outcome]],
) -> str | None:
    rejected_balances = [row for row in balances_for.get(legacy_id, []) if row.status == "rejected"]
    if rejected_balances and rejected_balances[0].reason:
        return rejected_balances[0].reason
    ready_services = [row for row in services_for.get(legacy_id, []) if row.status == "ready"]
    if ready_services:
        return None
    rejected_services = [row for row in services_for.get(legacy_id, []) if row.status == "rejected"]
    if rejected_services and rejected_services[0].reason:
        return rejected_services[0].reason
    return "no_service"
