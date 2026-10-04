"""Mutations that plant one labelled fault onto an otherwise consistent account.

Each planter changes the smallest set of rows that makes the fault true, then
recomputes the bill header so line totals still add up. The answer key records
what a reviewer should find and, where the fix is a credit, the INR amount.
"""

from datetime import timedelta
from decimal import Decimal

from billpilot.billing import ZERO, add_months, at_noon, credit_for_removing, money, quantity, rate
from billpilot.synthetic.catalog import (
    CALLER_TUNE,
    OTT_MINI,
    PROMO_CODE,
    PROMO_DATA_MB,
    PROMO_MONTHS,
    ROAM_ASIA,
    ROAM_WORLD,
)
from billpilot.synthetic.records import (
    Bundle,
    add_balance,
    add_entitlement,
    add_line,
    add_pack,
    add_usage,
    add_vas,
    anomaly_record,
    recompute_invoice,
    stamp,
    sync_paid_amount,
)


def plant_billing_fault(bundle: Bundle, anomaly_type: str, sequence: int) -> dict:
    planter = PLANTERS[anomaly_type]
    return planter(bundle, sequence)


def _latest(bundle: Bundle):
    return bundle.periods[-1], bundle.invoices[-1]


def _finish_paid(bundle: Bundle, invoice: dict) -> None:
    recompute_invoice(bundle, invoice)
    sync_paid_amount(bundle, invoice)


def _ids(rows: list[dict]) -> list[str]:
    return [str(row["id"]) for row in rows]


def plant_double_charge(bundle: Bundle, sequence: int) -> dict:
    _period, invoice = _latest(bundle)
    rental = next(
        line for line in bundle.lines if line["invoice_id"] == invoice["id"] and line["charge_type"] == "recurring"
    )
    duplicate = dict(rental)
    duplicate["id"] = bundle.ids.uuid("invoice-line", bundle.index, "rental-dup", sequence)
    duplicate["line_number"] = 50
    bundle.lines.append(duplicate)
    _finish_paid(bundle, invoice)
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], rental["amount"])
    return anomaly_record(
        bundle,
        "double_charge",
        sequence,
        "The latest invoice has two identical monthly rental lines.",
        "Credit one of the duplicate rental lines, including the GST charged on it.",
        credit,
        invoice,
        {"invoice_line_ids": [str(rental["id"]), str(duplicate["id"])]},
    )


def plant_roaming_spike(bundle: Bundle, sequence: int) -> dict:
    first = bundle.periods[0]
    last = bundle.periods[-1]
    baseline = add_usage(
        bundle,
        "roaming_data",
        stamp(first[0], 12),
        Decimal("40"),
        first,
        None,
        "Singapore",
        ("spike-baseline",),
    )
    spike = add_usage(
        bundle,
        "roaming_data",
        stamp(last[0], 12),
        Decimal("10000"),
        last,
        None,
        "Singapore",
        ("spike",),
    )
    _append_usage_line(bundle, bundle.invoices[0], baseline)
    _append_usage_line(bundle, bundle.invoices[-1], spike)
    _finish_paid(bundle, bundle.invoices[0])
    _finish_paid(bundle, bundle.invoices[-1])
    detected = spike["started_at"]
    bundle.flags.append(
        {
            "id": bundle.ids.uuid("fraud", bundle.index, "roaming"),
            "account_id": bundle.account["id"],
            "subscription_id": bundle.subscription["id"],
            "flag_type": "roaming_spike",
            "severity": "high",
            "status": "open",
            "detected_at": detected,
            "evidence": {
                "baseline_event_id": str(baseline["id"]),
                "spike_event_id": str(spike["id"]),
                "baseline_mb": "40.000",
                "spike_mb": "10000.000",
                "country": "Singapore",
            },
        }
    )
    return anomaly_record(
        bundle,
        "roaming_spike",
        sequence,
        "Roaming data in the latest cycle is far above this subscription's earlier cycles.",
        "Review the spike with the customer before any credit. Do not auto-credit.",
        None,
        bundle.invoices[-1],
        {"usage_event_ids": [str(baseline["id"]), str(spike["id"])], "fraud_flag_id": str(bundle.flags[-1]["id"])},
    )


def plant_wrong_rate(bundle: Bundle, sequence: int) -> dict:
    _period, invoice = _latest(bundle)
    line = _data_overage(bundle, invoice)
    correct = money(Decimal(line["quantity"]) * bundle.tariff.data_overage_rate)
    line["unit_price"] = rate(bundle.tariff.data_overage_rate * 10)
    line["amount"] = money(Decimal(line["quantity"]) * Decimal(line["unit_price"]))
    _finish_paid(bundle, invoice)
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], money(line["amount"] - correct))
    return anomaly_record(
        bundle,
        "wrong_rate",
        sequence,
        "A data overage line was priced at ten times the plan's data rate.",
        "Reprice the line at the catalogue data rate and credit the difference, including GST.",
        credit,
        invoice,
        {
            "invoice_line_id": str(line["id"]),
            "usage_event_id": str(line["usage_event_id"]),
            "catalogue_rate": f"{bundle.tariff.data_overage_rate:.4f}",
        },
    )


def plant_missed_discount(bundle: Bundle, sequence: int) -> dict:
    _period, invoice = _latest(bundle)
    discount = next(
        line for line in bundle.lines if line["invoice_id"] == invoice["id"] and line["charge_type"] == "discount"
    )
    missing = money(-Decimal(discount["amount"]))
    bundle.lines = [line for line in bundle.lines if line["id"] != discount["id"]]
    _finish_paid(bundle, invoice)
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], missing)
    return anomaly_record(
        bundle,
        "missed_discount",
        sequence,
        "The subscription has a loyalty discount, but the latest invoice has no discount line.",
        "Apply the loyalty discount and credit the missed amount, including GST.",
        credit,
        invoice,
        {"discount_percent": f"{Decimal(bundle.subscription['discount_percent']):.2f}"},
    )


def plant_charge_after_cancellation(bundle: Bundle, sequence: int) -> dict:
    period, invoice = _latest(bundle)
    ended = stamp(period[0], 2)
    bundle.subscription["ended_at"] = ended
    bundle.subscription["status"] = "cancelled"
    event = add_usage(
        bundle,
        "roaming_data",
        stamp(period[0], 20),
        Decimal("40"),
        period,
        None,
        "Thailand",
        ("after-cancel",),
    )
    line = _append_usage_line(bundle, invoice, event)
    rental = next(
        row for row in bundle.lines if row["invoice_id"] == invoice["id"] and row["charge_type"] == "recurring"
    )
    _finish_paid(bundle, invoice)
    total_days = Decimal((period[1] - period[0]).days)
    used_days = Decimal((ended.date() - period[0]).days)
    prorated = money(bundle.tariff.monthly_fee * used_days / total_days)
    unearned = money(rental["amount"] - prorated)
    pre_tax = money(unearned + line["amount"])
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], pre_tax)
    return anomaly_record(
        bundle,
        "charge_after_cancellation",
        sequence,
        "The subscription ended during the cycle, but the bill still has a full rental and usage after the end.",
        "Prorate the rental to the cancellation date and credit usage after that date, including GST.",
        credit,
        invoice,
        {
            "invoice_line_ids": [str(rental["id"]), str(line["id"])],
            "usage_event_id": str(event["id"]),
            "ended_at": ended.isoformat(),
        },
    )


def plant_vas_not_opted_in(bundle: Bundle, sequence: int) -> dict:
    period, invoice = _latest(bundle)
    vas = add_vas(bundle, CALLER_TUNE, at_noon(period[0]), False, "active", ("unwanted",))
    line = add_line(
        bundle,
        invoice,
        charge_type="vas",
        description=vas["name"],
        qty=Decimal("1"),
        unit_price=vas["monthly_fee"],
        amount=vas["monthly_fee"],
        key=("unwanted-vas",),
    )
    _finish_paid(bundle, invoice)
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], vas["monthly_fee"])
    return anomaly_record(
        bundle,
        "vas_not_opted_in",
        sequence,
        "Caller tune was charged even though the customer did not opt in.",
        "Credit the caller-tune charge, including GST, and stop the service.",
        credit,
        invoice,
        {"vas_id": str(vas["id"]), "invoice_line_id": str(line["id"])},
    )


def plant_payment_not_recorded(bundle: Bundle, sequence: int) -> dict:
    _period, invoice = _latest(bundle)
    attempted = invoice["created_at"] + timedelta(days=2)
    attempt = {
        "id": bundle.ids.uuid("attempt", bundle.index, "missing-payment"),
        "account_id": bundle.account["id"],
        "invoice_id": invoice["id"],
        "payment_id": None,
        "attempt_number": 1,
        "amount": invoice["total"],
        "method": "autopay",
        "status": "succeeded",
        "failure_reason": None,
        "attempted_at": attempted,
    }
    bundle.attempts.append(attempt)
    invoice["amount_due"] = invoice["total"]
    invoice["status"] = "issued"
    return anomaly_record(
        bundle,
        "payment_not_recorded",
        sequence,
        "Autopay succeeded, but no payment row was recorded and the bill is still open.",
        "Record and post the payment, then clear the amount due.",
        None,
        invoice,
        {"payment_attempt_id": str(attempt["id"]), "amount_inr": f"{invoice['total']:.2f}"},
    )


def plant_payment_not_posted(bundle: Bundle, sequence: int) -> dict:
    _period, invoice = _latest(bundle)
    received = invoice["created_at"] + timedelta(days=2)
    payment_id = bundle.ids.uuid("payment", bundle.index, "unposted")
    payment = {
        "id": payment_id,
        "account_id": bundle.account["id"],
        "invoice_id": invoice["id"],
        "payment_number": f"PAY-{bundle.index + 1:06d}-UNPOSTED",
        "amount": invoice["total"],
        "method": "upi",
        "status": "received",
        "reference": f"REF-{bundle.index + 1:06d}-UNPOSTED",
        "received_at": received,
        "posted_at": None,
        "currency": "INR",
        "created_at": received,
    }
    bundle.payments.append(payment)
    bundle.attempts.append(
        {
            "id": bundle.ids.uuid("attempt", bundle.index, "unposted"),
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_id": payment_id,
            "attempt_number": 1,
            "amount": invoice["total"],
            "method": "upi",
            "status": "succeeded",
            "failure_reason": None,
            "attempted_at": received,
        }
    )
    invoice["amount_due"] = invoice["total"]
    invoice["status"] = "issued"
    return anomaly_record(
        bundle,
        "payment_not_posted",
        sequence,
        "A payment was received for the full bill but never posted, so the amount due is unchanged.",
        "Post the payment and reduce the amount due to zero.",
        None,
        invoice,
        {"payment_id": str(payment_id), "amount_inr": f"{invoice['total']:.2f}"},
    )


def plant_unbilled_usage(bundle: Bundle, sequence: int) -> dict:
    _period, invoice = _latest(bundle)
    line = _data_overage(bundle, invoice)
    event = next(row for row in bundle.events if row["id"] == line["usage_event_id"])
    event["billed"] = False
    event["rating_status"] = "unbilled"
    bundle.lines = [row for row in bundle.lines if row["id"] != line["id"]]
    _finish_paid(bundle, invoice)
    return anomaly_record(
        bundle,
        "unbilled_usage",
        sequence,
        "Rated usage in a billed cycle never landed on the invoice.",
        "Add the usage to a supplementary bill or the next bill. This is not a credit.",
        None,
        invoice,
        {"usage_event_id": str(event["id"]), "unbilled_amount_inr": f"{event['rated_amount']:.2f}"},
    )


def plant_duplicate_usage(bundle: Bundle, sequence: int) -> dict:
    _period, invoice = _latest(bundle)
    original_line = _data_overage(bundle, invoice)
    original = next(row for row in bundle.events if row["id"] == original_line["usage_event_id"])
    clone = dict(original)
    clone["id"] = bundle.ids.uuid("usage", bundle.index, "dup-event")
    clone["rating_status"] = "duplicate"
    clone["source_event_id"] = original["source_event_id"]
    clone["billed"] = True
    bundle.events.append(clone)
    clone_line = _append_usage_line(bundle, invoice, clone)
    _finish_paid(bundle, invoice)
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], clone_line["amount"])
    return anomaly_record(
        bundle,
        "duplicate_usage",
        sequence,
        "Two rated usage records share one source event id and both were billed.",
        "Drop the duplicate record and credit the extra charge, including GST.",
        credit,
        invoice,
        {
            "usage_event_ids": [str(original["id"]), str(clone["id"])],
            "source_event_id": original["source_event_id"],
            "invoice_line_ids": [str(original_line["id"]), str(clone_line["id"])],
        },
    )


def plant_sim_swap(bundle: Bundle, sequence: int) -> dict:
    period, invoice = _latest(bundle)
    old_sim = bundle.subscription["sim_serial"]
    old_imsi = bundle.subscription["imsi"]
    new_sim = f"{8991200000000000000 + bundle.index}"
    new_imsi = f"405{bundle.index:012d}"
    swapped_at = stamp(period[0], 4, hour=10)
    bundle.subscription["sim_serial"] = new_sim
    bundle.subscription["imsi"] = new_imsi
    burst = []
    for slot in range(8):
        event = add_usage(
            bundle,
            "voice",
            swapped_at + timedelta(minutes=5 * slot),
            Decimal("1"),
            period,
            "premium-rate",
            None,
            ("swap", slot),
        )
        event["billed"] = True
        burst.append(event)
    flag = {
        "id": bundle.ids.uuid("fraud", bundle.index, "sim-swap"),
        "account_id": bundle.account["id"],
        "subscription_id": bundle.subscription["id"],
        "flag_type": "sim_swap",
        "severity": "high",
        "status": "open",
        "detected_at": swapped_at,
        "evidence": {
            "old_sim_serial": old_sim,
            "new_sim_serial": new_sim,
            "old_imsi": old_imsi,
            "new_imsi": new_imsi,
            "swapped_at": swapped_at.isoformat(),
            "burst_event_ids": _ids(burst),
        },
    }
    bundle.flags.append(flag)
    return anomaly_record(
        bundle,
        "sim_swap",
        sequence,
        "The SIM and IMSI changed, then a short burst of premium-rate calls followed.",
        "Treat this as a SIM-swap investigation. Do not auto-credit or auto-bar from this flag alone.",
        None,
        invoice,
        {"fraud_flag_id": str(flag["id"]), "usage_event_ids": _ids(burst)},
    )


def plant_addon_never_activated(bundle: Bundle, sequence: int) -> dict:
    period, invoice = _latest(bundle)
    pack = add_pack(bundle, ROAM_ASIA, stamp(period[0], 1), ROAM_ASIA["days"], ("never",))
    entitlement = add_entitlement(
        bundle,
        "roaming_pack",
        str(pack["id"]),
        "roaming_data",
        Decimal(pack["data_mb"]),
        "MB",
        "pending_activation",
        pack["valid_from"],
        pack["valid_to"],
        False,
        ("never-ent",),
    )
    line = add_line(
        bundle,
        invoice,
        charge_type="addon",
        description=pack["name"],
        qty=Decimal("1"),
        unit_price=pack["price"],
        amount=pack["price"],
        key=("never-pack",),
    )
    _finish_paid(bundle, invoice)
    return anomaly_record(
        bundle,
        "addon_never_activated",
        sequence,
        "A roaming pack was paid for, but its entitlement is still pending activation and has no balance.",
        "Activate the pack and create the allowance. Credit only if the travel window has already passed.",
        None,
        invoice,
        {
            "roaming_pack_id": str(pack["id"]),
            "entitlement_id": str(entitlement["id"]),
            "invoice_line_id": str(line["id"]),
        },
    )


def plant_allowance_not_reset(bundle: Bundle, sequence: int) -> dict:
    entitlement = next(
        row for row in bundle.entitlements if row["feature_code"] == "data" and row["source_type"] == "plan"
    )
    balances = [row for row in bundle.balances if row["entitlement_id"] == entitlement["id"]]
    balances.sort(key=lambda row: row["period_start"])
    prior, latest = balances[-2], balances[-1]
    if prior["consumed_quantity"] == 0:
        prior["consumed_quantity"] = quantity(Decimal("100"))
        prior["remaining_quantity"] = quantity(Decimal(prior["granted_quantity"]) - Decimal("100"))
    latest["consumed_quantity"] = prior["consumed_quantity"]
    latest["remaining_quantity"] = prior["remaining_quantity"]
    latest["reset_at"] = None
    new_usage = sum(
        (
            Decimal(event["quantity"])
            for event in bundle.events
            if event["event_type"] == "data" and event["period_start"] == latest["period_start"]
        ),
        ZERO,
    )
    if new_usage == Decimal(latest["consumed_quantity"]):
        for event in bundle.events:
            if event["event_type"] == "data" and event["period_start"] == latest["period_start"]:
                event["quantity"] = quantity(Decimal(event["quantity"]) + Decimal("5"))
                break
    return anomaly_record(
        bundle,
        "allowance_not_reset",
        sequence,
        "The data allowance was not reset on the bill date; the new cycle still shows the previous balance.",
        "Reset the balance to the full grant on the bill date and re-rate the cycle if the customer was overcharged.",
        None,
        bundle.invoices[-1],
        {
            "entitlement_id": str(entitlement["id"]),
            "balance_ids": [str(prior["id"]), str(latest["id"])],
        },
    )


def plant_overlapping(bundle: Bundle, sequence: int, dropped: bool) -> dict:
    period, invoice = _latest(bundle)
    start = stamp(period[0], 1)
    first = add_pack(bundle, ROAM_ASIA, start, 10, ("overlap-a",))
    second = add_pack(bundle, ROAM_WORLD, start + timedelta(days=4), 10, ("overlap-b",))
    for pack in (first, second):
        add_line(
            bundle,
            invoice,
            charge_type="addon",
            description=pack["name"],
            qty=Decimal("1"),
            unit_price=pack["price"],
            amount=pack["price"],
            key=("overlap-line", pack["pack_code"]),
        )
    if dropped:
        allowance = Decimal(first["data_mb"])
        source_ref = str(first["id"])
        anomaly_type = "overlapping_packs_dropped"
        finding = "Two overlapping roaming packs were paid for, but only one allowance was created."
        correction = "Create the missing pack allowance, or credit the pack that was dropped."
    else:
        allowance = Decimal(first["data_mb"] + second["data_mb"])
        source_ref = f"{first['id']}+{second['id']}"
        anomaly_type = "overlapping_packs_double_counted"
        finding = "Two overlapping roaming packs were added into a single allowance."
        correction = "Keep separate buckets. Do not sum overlapping packs into one grant."
    entitlement = add_entitlement(
        bundle,
        "roaming_pack",
        source_ref,
        "roaming_data",
        allowance,
        "MB",
        "active",
        first["valid_from"],
        second["valid_to"],
        False,
        ("overlap-ent", anomaly_type),
    )
    add_balance(
        bundle,
        entitlement,
        (first["valid_from"].date(), (second["valid_to"].date() + timedelta(days=1))),
        allowance,
        first["valid_from"],
        ("overlap-bal", anomaly_type),
    )
    _finish_paid(bundle, invoice)
    return anomaly_record(
        bundle,
        anomaly_type,
        sequence,
        finding,
        correction,
        None,
        invoice,
        {
            "roaming_pack_ids": [str(first["id"]), str(second["id"])],
            "entitlement_id": str(entitlement["id"]),
        },
    )


def plant_overlapping_double(bundle: Bundle, sequence: int) -> dict:
    return plant_overlapping(bundle, sequence, dropped=False)


def plant_overlapping_dropped(bundle: Bundle, sequence: int) -> dict:
    return plant_overlapping(bundle, sequence, dropped=True)


def plant_promo_ended_early(bundle: Bundle, sequence: int) -> dict:
    start = bundle.periods[0][0]
    valid_from = at_noon(start)
    valid_to = at_noon(add_months(start, 1))
    entitlement = add_entitlement(
        bundle,
        "promo",
        PROMO_CODE,
        "data",
        Decimal(PROMO_DATA_MB),
        "MB",
        "expired",
        valid_from,
        valid_to,
        False,
        ("promo",),
    )
    return anomaly_record(
        bundle,
        "promo_ended_early",
        sequence,
        f"{PROMO_CODE} is a {PROMO_MONTHS}-month data bonus, but the entitlement ended after one month.",
        "Restore the promotional end date to three months from the start and reinstate any bonus that was removed.",
        None,
        bundle.invoices[-1],
        {
            "entitlement_id": str(entitlement["id"]),
            "promo_code": PROMO_CODE,
            "planned_months": str(PROMO_MONTHS),
        },
    )


def plant_feature_active_after_cancellation(bundle: Bundle, sequence: int) -> dict:
    ended = bundle.subscription["ended_at"]
    vas = add_vas(bundle, OTT_MINI, bundle.subscription["started_at"], True, "cancelled", ("ott-cancelled",), ended)
    entitlement = add_entitlement(
        bundle,
        "vas",
        OTT_MINI["code"],
        "ott_mini",
        Decimal("1"),
        "feature",
        "active",
        bundle.subscription["started_at"],
        None,
        False,
        ("ott-still-active",),
    )
    return anomaly_record(
        bundle,
        "feature_active_after_cancellation",
        sequence,
        "The mobile subscription and the OTT add-on are cancelled, but the OTT feature entitlement is still active.",
        "Cancel the feature entitlement as of the subscription end date.",
        None,
        bundle.invoices[-1] if bundle.invoices else None,
        {"vas_id": str(vas["id"]), "entitlement_id": str(entitlement["id"])},
    )


def plant_overage_on_covered_usage(bundle: Bundle, sequence: int) -> dict:
    period, invoice = _latest(bundle)
    event = next(
        row
        for row in bundle.events
        if row["event_type"] == "data" and row["period_start"] == period[0] and row["rated_amount"] == 0
    )
    balance = next(
        row
        for row in bundle.balances
        if row["period_start"] == period[0]
        and any(ent["id"] == row["entitlement_id"] and ent["feature_code"] == "data" for ent in bundle.entitlements)
    )
    balance["consumed_quantity"] = quantity(Decimal(balance["consumed_quantity"]) - Decimal(event["quantity"]))
    balance["remaining_quantity"] = quantity(Decimal(balance["remaining_quantity"]) + Decimal(event["quantity"]))
    applied = bundle.tariff.data_overage_rate
    event["rate_applied"] = rate(applied)
    event["rated_amount"] = money(Decimal(event["quantity"]) * applied)
    event["billed"] = True
    line = _append_usage_line(bundle, invoice, event)
    _finish_paid(bundle, invoice)
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], line["amount"])
    return anomaly_record(
        bundle,
        "overage_on_covered_usage",
        sequence,
        "Data usage was charged as overage even though the remaining allowance covered it.",
        "Zero the overage line and credit it, including GST. Consume the allowance instead.",
        credit,
        invoice,
        {
            "usage_event_id": str(event["id"]),
            "invoice_line_id": str(line["id"]),
            "balance_id": str(balance["id"]),
        },
    )


def _data_overage(bundle: Bundle, invoice: dict) -> dict:
    return next(
        line for line in bundle.lines if line["invoice_id"] == invoice["id"] and line["description"] == "Data overage"
    )


def _append_usage_line(bundle: Bundle, invoice: dict, event: dict) -> dict:
    charge_type = "roaming" if event["event_type"].startswith("roaming") else "usage"
    description = {
        "voice": "Voice overage",
        "data": "Data overage",
        "sms": "SMS overage",
        "roaming_voice": "Roaming voice",
        "roaming_data": "Roaming data",
        "roaming_sms": "Roaming SMS",
    }[event["event_type"]]
    event["billed"] = True
    overage_qty = quantity(Decimal(event["rated_amount"]) / Decimal(event["rate_applied"]))
    amount = money(overage_qty * Decimal(event["rate_applied"]))
    event["rated_amount"] = amount
    return add_line(
        bundle,
        invoice,
        charge_type=charge_type,
        description=description,
        qty=overage_qty,
        unit_price=event["rate_applied"],
        amount=amount,
        usage_event_id=event["id"],
        tariff_plan_id=bundle.subscription["tariff_plan_id"],
        key=("extra", event["id"]),
    )


PLANTERS = {
    "double_charge": plant_double_charge,
    "roaming_spike": plant_roaming_spike,
    "wrong_rate": plant_wrong_rate,
    "missed_discount": plant_missed_discount,
    "charge_after_cancellation": plant_charge_after_cancellation,
    "vas_not_opted_in": plant_vas_not_opted_in,
    "payment_not_recorded": plant_payment_not_recorded,
    "payment_not_posted": plant_payment_not_posted,
    "unbilled_usage": plant_unbilled_usage,
    "duplicate_usage": plant_duplicate_usage,
    "sim_swap": plant_sim_swap,
    "addon_never_activated": plant_addon_never_activated,
    "allowance_not_reset": plant_allowance_not_reset,
    "overlapping_packs_double_counted": plant_overlapping_double,
    "overlapping_packs_dropped": plant_overlapping_dropped,
    "promo_ended_early": plant_promo_ended_early,
    "feature_active_after_cancellation": plant_feature_active_after_cancellation,
    "overage_on_covered_usage": plant_overage_on_covered_usage,
}
