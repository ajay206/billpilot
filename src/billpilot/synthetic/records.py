"""Row builders and the per-customer bundle the planters mutate before insert."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from billpilot.billing import ZERO, at_noon, gst, money, quantity, rate
from billpilot.schema import INSERT_ORDER
from billpilot.synthetic.ids import IdFactory

EVENT_UNIT = {
    "voice": "minute",
    "data": "MB",
    "sms": "message",
    "roaming_voice": "minute",
    "roaming_data": "MB",
    "roaming_sms": "message",
}


class World:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = {name: [] for name in INSERT_ORDER}
        self.anomalies: list[dict] = []
        self.controls: list[dict] = []
        self.plan_ids: dict[str, object] = {}
        self.treatment_plan_id = None


class Bundle:
    """Everything one customer owns, still mutable, not yet attached to the world."""

    def __init__(self, world: World, ids: IdFactory, index: int) -> None:
        self.world = world
        self.ids = ids
        self.index = index
        self.customer: dict | None = None
        self.account: dict | None = None
        self.subscription: dict | None = None
        self.tariff = None
        self.events: list[dict] = []
        self.invoices: list[dict] = []
        self.lines: list[dict] = []
        self.payments: list[dict] = []
        self.attempts: list[dict] = []
        self.vas: list[dict] = []
        self.packs: list[dict] = []
        self.entitlements: list[dict] = []
        self.balances: list[dict] = []
        self.tickets: list[dict] = []
        self.disputes: list[dict] = []
        self.treatments: list[dict] = []
        self.exemptions: list[dict] = []
        self.dunning: list[dict] = []
        self.flags: list[dict] = []

    def flush(self) -> None:
        rows = self.world.rows
        rows["customers"].append(self.customer)
        rows["accounts"].append(self.account)
        rows["subscriptions"].append(self.subscription)
        rows["usage_events"].extend(self.events)
        rows["invoices"].extend(self.invoices)
        rows["invoice_lines"].extend(self.lines)
        rows["payments"].extend(self.payments)
        rows["payment_attempts"].extend(self.attempts)
        rows["vas_subscriptions"].extend(self.vas)
        rows["roaming_packs"].extend(self.packs)
        rows["entitlements"].extend(self.entitlements)
        rows["entitlement_balances"].extend(self.balances)
        rows["tickets"].extend(self.tickets)
        rows["disputes"].extend(self.disputes)
        rows["account_treatment"].extend(self.treatments)
        rows["treatment_exemptions"].extend(self.exemptions)
        rows["dunning_events"].extend(self.dunning)
        rows["fraud_flags"].extend(self.flags)


def stamp(period_start: date, day: int, hour: int = 10, minute: int = 0) -> datetime:
    return at_noon(period_start).replace(hour=hour, minute=minute) + timedelta(days=day)


def recompute_invoice(bundle: Bundle, invoice: dict) -> None:
    """Rebuild the GST line and the header from the other lines. Safe to call again."""
    kept: list[dict] = []
    mine: list[dict] = []
    for line in bundle.lines:
        if line["invoice_id"] != invoice["id"]:
            kept.append(line)
        elif line["charge_type"] != "tax":
            mine.append(line)
    mine.sort(key=lambda line: (line["line_number"], str(line["id"])))
    for number, line in enumerate(mine, start=1):
        line["line_number"] = number
    subtotal = money(sum((line["amount"] for line in mine), ZERO))
    tax = gst(subtotal)
    tax_line = invoice_line(
        bundle,
        invoice["id"],
        len(mine) + 1,
        "tax",
        "GST 18%",
        Decimal("1"),
        tax,
        tax,
        usage_event_id=None,
        tariff_plan_id=None,
        key=("tax", invoice["id"]),
    )
    bundle.lines = kept + mine + [tax_line]
    invoice["subtotal"] = subtotal
    invoice["tax"] = tax
    invoice["total"] = money(subtotal + tax)


def sync_paid_amount(bundle: Bundle, invoice: dict) -> None:
    """Point the posted payment at the current total so the books still balance."""
    payment = next(row for row in bundle.payments if row["invoice_id"] == invoice["id"])
    payment["amount"] = invoice["total"]
    payment["status"] = "posted"
    payment["posted_at"] = payment["received_at"]
    for attempt in bundle.attempts:
        if attempt["payment_id"] == payment["id"]:
            attempt["amount"] = invoice["total"]
    invoice["amount_due"] = ZERO
    invoice["status"] = "paid"


def invoice_line(
    bundle: Bundle,
    invoice_id,
    line_number: int,
    charge_type: str,
    description: str,
    qty: Decimal,
    unit_price: Decimal,
    amount: Decimal,
    usage_event_id=None,
    tariff_plan_id=None,
    key: tuple = (),
) -> dict:
    return {
        "id": bundle.ids.uuid("invoice-line", bundle.index, *key),
        "invoice_id": invoice_id,
        "line_number": line_number,
        "charge_type": charge_type,
        "description": description,
        "quantity": quantity(qty),
        "unit_price": rate(unit_price),
        "amount": money(amount),
        "subscription_id": bundle.subscription["id"],
        "usage_event_id": usage_event_id,
        "tariff_plan_id": tariff_plan_id,
    }


def add_line(bundle: Bundle, invoice: dict, **kwargs) -> dict:
    existing = [line for line in bundle.lines if line["invoice_id"] == invoice["id"]]
    line = invoice_line(bundle, invoice["id"], len(existing) + 1, **kwargs)
    bundle.lines.append(line)
    return line


def cover(balance: dict, qty: Decimal) -> Decimal:
    take = min(Decimal(balance["remaining_quantity"]), qty)
    balance["remaining_quantity"] = quantity(Decimal(balance["remaining_quantity"]) - take)
    balance["consumed_quantity"] = quantity(Decimal(balance["consumed_quantity"]) + take)
    return quantity(qty - take)


def balances_covering(bundle: Bundle, feature: str, when: datetime) -> list[dict]:
    found = []
    entitlements = {row["id"]: row for row in bundle.entitlements}
    for balance in bundle.balances:
        entitlement = entitlements[balance["entitlement_id"]]
        # A balance row is the grant for that window. Pending add-ons have no row yet,
        # so they are skipped without a second status check.
        if entitlement["feature_code"] != feature:
            continue
        start = at_noon(balance["period_start"])
        end = at_noon(balance["period_end"])
        if start <= when < end:
            found.append(balance)
    return found


def add_usage(
    bundle: Bundle,
    event_type: str,
    when: datetime,
    qty: Decimal,
    period: tuple[date, date],
    destination: str | None,
    country: str | None,
    key: tuple,
) -> dict:
    unit = EVENT_UNIT[event_type]
    applied = bundle.tariff.overage_rate(event_type)
    feature = event_type
    remaining = quantity(qty)
    for balance in balances_covering(bundle, feature, when):
        remaining = cover(balance, remaining)
        if remaining == 0:
            break
    rated_amount = money(remaining * applied) if remaining > 0 else ZERO
    if event_type == "voice" or event_type == "roaming_voice":
        ended = when + timedelta(minutes=int(qty))
    elif event_type in {"data", "roaming_data"}:
        ended = when + timedelta(hours=1)
    else:
        ended = when
    event = {
        "id": bundle.ids.uuid("usage", bundle.index, *key),
        "subscription_id": bundle.subscription["id"],
        "event_type": event_type,
        "started_at": when,
        "ended_at": ended,
        "quantity": quantity(qty),
        "unit": unit,
        "rate_applied": rate(applied),
        "rated_amount": rated_amount,
        "roaming_country": country,
        "destination": destination,
        "billed": False,
        "rating_status": "rated",
        "source_event_id": "",
        "period_start": period[0],
        "period_end": period[1],
        "created_at": when,
    }
    event["source_event_id"] = str(event["id"])
    bundle.events.append(event)
    return event


def add_entitlement(
    bundle: Bundle,
    source_type: str,
    source_ref: str,
    feature_code: str,
    allowance: Decimal,
    unit: str,
    status: str,
    valid_from: datetime,
    valid_to: datetime | None,
    resets: bool,
    key: tuple,
) -> dict:
    row = {
        "id": bundle.ids.uuid("entitlement", bundle.index, *key),
        "subscription_id": bundle.subscription["id"],
        "source_type": source_type,
        "source_ref": source_ref,
        "feature_code": feature_code,
        "allowance_quantity": quantity(allowance),
        "unit": unit,
        "status": status,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "resets_on_bill_cycle": resets,
        "created_at": valid_from,
    }
    bundle.entitlements.append(row)
    return row


def add_balance(
    bundle: Bundle,
    entitlement: dict,
    period: tuple[date, date],
    granted: Decimal,
    reset_at: datetime | None,
    key: tuple,
) -> dict:
    row = {
        "id": bundle.ids.uuid("balance", bundle.index, *key),
        "entitlement_id": entitlement["id"],
        "period_start": period[0],
        "period_end": period[1],
        "granted_quantity": quantity(granted),
        "consumed_quantity": quantity(ZERO),
        "remaining_quantity": quantity(granted),
        "reset_at": reset_at,
    }
    bundle.balances.append(row)
    return row


def add_ticket(
    bundle: Bundle,
    summary: str,
    description: str,
    opened_at: datetime,
    ticket_type: str,
    key: tuple,
    severity: str = "Minor",
) -> dict:
    row = {
        "id": bundle.ids.uuid("ticket", bundle.index, *key),
        "account_id": bundle.account["id"],
        "ticket_number": f"TCK-{bundle.index + 1:06d}-{key[0]}",
        "ticket_type": ticket_type,
        "severity": severity,
        "status": "open",
        "summary": summary,
        "description": description,
        "opened_by": "generator",
        "opened_at": opened_at,
    }
    bundle.tickets.append(row)
    return row


def add_dispute(
    bundle: Bundle,
    invoice: dict | None,
    ticket: dict | None,
    category: str,
    description: str,
    opened_at: datetime,
    key: tuple,
    status: str = "open",
) -> dict:
    row = {
        "id": bundle.ids.uuid("dispute", bundle.index, *key),
        "account_id": bundle.account["id"],
        "invoice_id": None if invoice is None else invoice["id"],
        "ticket_id": None if ticket is None else ticket["id"],
        "status": status,
        "category": category,
        "description": description,
        "opened_by": "generator",
        "opened_at": opened_at,
        "resolved_at": None,
    }
    bundle.disputes.append(row)
    return row


def add_treatment(
    bundle: Bundle,
    stage: str,
    status: str,
    started_at: datetime,
    hold_reason: str | None,
    key: tuple,
) -> dict:
    row = {
        "id": bundle.ids.uuid("treatment", bundle.index, *key),
        "account_id": bundle.account["id"],
        "treatment_plan_id": bundle.world.treatment_plan_id,
        "stage": stage,
        "status": status,
        "started_at": started_at,
        "hold_reason": hold_reason,
        "updated_at": started_at,
    }
    bundle.treatments.append(row)
    return row


def add_dunning(
    bundle: Bundle,
    treatment: dict,
    event_type: str,
    occurred_at: datetime,
    notes: str,
    key: tuple,
    promise_pay_by: datetime | None = None,
    promise_amount: Decimal | None = None,
) -> dict:
    row = {
        "id": bundle.ids.uuid("dunning", bundle.index, *key),
        "account_id": bundle.account["id"],
        "account_treatment_id": treatment["id"],
        "event_type": event_type,
        "occurred_at": occurred_at,
        "notes": notes,
        "promise_pay_by": promise_pay_by,
        "promise_amount": promise_amount,
    }
    bundle.dunning.append(row)
    return row


def add_pack(bundle: Bundle, spec: dict, valid_from: datetime, days: int, key: tuple, status: str = "active") -> dict:
    row = {
        "id": bundle.ids.uuid("pack", bundle.index, *key),
        "subscription_id": bundle.subscription["id"],
        "pack_code": spec["code"],
        "name": spec["name"],
        "zone": spec["zone"],
        "data_mb": spec["data_mb"],
        "voice_minutes": spec["voice_minutes"],
        "price": money(spec["price"]),
        "valid_from": valid_from,
        "valid_to": valid_from + timedelta(days=days),
        "status": status,
    }
    bundle.packs.append(row)
    return row


def add_vas(
    bundle: Bundle,
    spec: dict,
    started_at: datetime,
    opted_in: bool,
    status: str,
    key: tuple,
    ended_at=None,
) -> dict:
    row = {
        "id": bundle.ids.uuid("vas", bundle.index, *key),
        "subscription_id": bundle.subscription["id"],
        "product_code": spec["code"],
        "name": spec["name"],
        "monthly_fee": money(spec["monthly_fee"]),
        "opted_in": opted_in,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    bundle.vas.append(row)
    return row


def anomaly_record(
    bundle: Bundle,
    anomaly_type: str,
    sequence: int,
    finding: str,
    correction: str,
    credit: Decimal | None,
    invoice: dict | None,
    related: dict,
) -> dict:
    return {
        "id": f"{anomaly_type}-{sequence:03d}",
        "type": anomaly_type,
        "customer_id": str(bundle.customer["id"]),
        "customer_number": bundle.customer["customer_number"],
        "account_id": str(bundle.account["id"]),
        "account_number": bundle.account["account_number"],
        "subscription_id": str(bundle.subscription["id"]),
        "invoice_id": None if invoice is None else str(invoice["id"]),
        "related_ids": related,
        "expected_finding": finding,
        "expected_correction": correction,
        "expected_credit_inr": None if credit is None else f"{credit:.2f}",
    }


def open_account(
    world: World,
    ids: IdFactory,
    index: int,
    given_name: str,
    family_name: str,
    city: str,
    state: str,
    plan_id,
    tariff,
    opened_at: datetime,
    cycle_day: int,
    discount: Decimal,
    status: str = "active",
    ended_at: datetime | None = None,
) -> Bundle:
    """Customer, account and one mobile subscription. Plan rows already live on the world."""
    bundle = Bundle(world, ids, index)
    national = f"{9000000000 + index:010d}"
    bundle.tariff = tariff
    bundle.customer = {
        "id": ids.uuid("customer", index),
        "customer_number": f"CUST-{index + 1:06d}",
        "given_name": given_name,
        "family_name": family_name,
        "email": f"cust{index + 1:06d}@example.com",
        "phone": f"+91{national}",
        "city": city,
        "state": state,
        "created_at": opened_at,
    }
    bundle.account = {
        "id": ids.uuid("account", index),
        "customer_id": bundle.customer["id"],
        "account_number": f"ACC-{index + 1:06d}",
        "status": "active" if status != "cancelled" else "active",
        "currency": "INR",
        "billing_cycle_day": cycle_day,
        "assigned_csr": "CSR-A" if index % 2 == 0 else "CSR-B",
        "opened_at": opened_at,
        "closed_at": None,
        "created_at": opened_at,
    }
    bundle.subscription = {
        "id": ids.uuid("subscription", index),
        "account_id": bundle.account["id"],
        "tariff_plan_id": plan_id,
        "msisdn": national,
        "imsi": f"404{index:012d}",
        "sim_serial": f"{8991100000000000000 + index}",
        "status": status,
        "discount_percent": money(discount),
        "started_at": opened_at,
        "ended_at": ended_at,
        "created_at": opened_at,
    }
    return bundle


def control_record(bundle: Bundle, control_type: str, finding: str, invoice: dict | None, related: dict) -> dict:
    return {
        "id": f"control-{control_type}",
        "type": control_type,
        "customer_id": str(bundle.customer["id"]),
        "customer_number": bundle.customer["customer_number"],
        "account_id": str(bundle.account["id"]),
        "account_number": bundle.account["account_number"],
        "subscription_id": str(bundle.subscription["id"]),
        "invoice_id": None if invoice is None else str(invoice["id"]),
        "related_ids": related,
        "expected_finding": finding,
    }
