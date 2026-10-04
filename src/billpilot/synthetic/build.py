"""Build an in-memory world of synthetic customers, bills and planted faults.

Nothing here reads the wall clock. Names come from Faker's en_IN locale, except
the three demo customers, whose names match their sign-in. Every other choice
comes from random.Random(seed) or from a fixed catalogue.
"""

import json
import random
from datetime import timedelta
from decimal import Decimal

from faker import Faker

from billpilot.auth.demo import holder_name_for_index
from billpilot.billing import (
    AS_OF,
    LATE_FEE,
    ZERO,
    TreatmentThresholds,
    add_months,
    at_noon,
    completed_periods,
    money,
    quantity,
    shift,
    stage_for_days,
    stages_reached,
    threshold_days,
)
from billpilot.synthetic.catalog import (
    CITIES,
    DOMESTIC_FEATURES,
    ROAM_ASIA,
    STANDARD_TREATMENT,
    TARIFFS,
    TARIFFS_BY_CODE,
)
from billpilot.synthetic.config import (
    ANOMALY_TYPES,
    CONTROL_TYPES,
    TREATMENT_ANOMALIES,
    GeneratorConfig,
)
from billpilot.synthetic.ids import IdFactory
from billpilot.synthetic.plant import plant_billing_fault
from billpilot.synthetic.records import (
    Bundle,
    World,
    add_balance,
    add_dunning,
    add_entitlement,
    add_line,
    add_pack,
    add_treatment,
    add_usage,
    add_vas,
    open_account,
    recompute_invoice,
    stamp,
)
from billpilot.synthetic.treatment import build_control, build_treatment_anomaly

METHODS = ("upi", "autopay", "upi", "card", "netbanking")
ROAMING_COUNTRIES = ("Singapore", "United Arab Emirates", "Thailand", "United Kingdom")
PAYMENT_FAULTS = frozenset({"payment_not_recorded", "payment_not_posted"})
SMALL_DATA = frozenset({"wrong_rate", "unbilled_usage", "duplicate_usage"})


def build_world(config: GeneratorConfig) -> World:
    config.validate()
    rng = random.Random(config.seed)
    fake = Faker("en_IN")
    fake.seed_instance(config.seed)
    ids = IdFactory(config.seed)
    world = World()
    _add_plans(world, ids)
    _add_treatment_plan(world, ids)
    _add_incidents(world, ids)

    anomalies, controls, delinquent = _place(config)
    for index in range(config.customer_count):
        given = fake.first_name()
        family = fake.last_name()
        # Draw the Faker name first so the rest of the sequence stays put, then
        # use the demo sign-in name for the three portfolio customers.
        override = holder_name_for_index(index)
        if override is not None:
            given, family = override
        city, state = CITIES[rng.randrange(len(CITIES))]
        if index in anomalies and anomalies[index][0] in TREATMENT_ANOMALIES:
            record = build_treatment_anomaly(world, ids, index, given, family, city, state, anomalies[index])
            world.anomalies.append(record)
            continue
        if index in controls:
            record = build_control(world, ids, index, given, family, city, state, controls[index])
            world.controls.append(record)
            continue
        anomaly = anomalies.get(index)
        bundle = _build_standard(
            world,
            ids,
            rng,
            index,
            given,
            family,
            city,
            state,
            None if anomaly is None else anomaly[0],
            config,
            index in delinquent,
        )
        if anomaly is not None:
            world.anomalies.append(plant_billing_fault(bundle, anomaly[0], anomaly[1]))
        bundle.flush()

    world.anomalies.sort(key=lambda row: row["id"])
    document = {
        "seed": config.seed,
        "as_of": AS_OF.isoformat(),
        "currency": "INR",
        "customer_count": config.customer_count,
        "months": config.months,
        "anomaly_counts": {name: config.anomaly_counts[name] for name in ANOMALY_TYPES},
        "anomalies": world.anomalies,
        "controls": world.controls,
    }
    world.ground_truth = json.loads(json.dumps(document, sort_keys=True))
    return world


def world_signature(world: World) -> str:
    payload = {
        "ground_truth": world.ground_truth,
        "ids": {table: [str(row["id"]) for row in rows] for table, rows in world.rows.items()},
        "invoice_totals": [str(row["total"]) for row in world.rows["invoices"]],
    }
    return json.dumps(payload, sort_keys=True)


def _place(config: GeneratorConfig):
    anomalies: dict[int, tuple[str, int]] = {}
    cursor = 1
    for name in ANOMALY_TYPES:
        for sequence in range(config.anomaly_counts[name]):
            anomalies[cursor] = (name, sequence + 1)
            cursor += 1
    controls: dict[int, str] = {}
    for name in CONTROL_TYPES:
        if cursor % 2 == 1:
            cursor += 1
        controls[cursor] = name
        cursor += 2
    occupied = set(anomalies) | set(controls) | {0}
    free = [index for index in range(cursor, config.customer_count) if index not in occupied]
    if len(free) < config.delinquent_count:
        raise ValueError("not enough free customers for delinquent_count")
    return anomalies, controls, free[: config.delinquent_count]


def _add_plans(world: World, ids: IdFactory) -> None:
    for tariff in TARIFFS:
        plan_id = ids.uuid("tariff", tariff.code)
        world.plan_ids[tariff.code] = plan_id
        world.rows["tariff_plans"].append(
            {
                "id": plan_id,
                "code": tariff.code,
                "name": tariff.name,
                "description": tariff.description,
                "monthly_fee": money(tariff.monthly_fee),
                "included_voice_minutes": tariff.included_voice_minutes,
                "included_data_mb": tariff.included_data_mb,
                "included_sms": tariff.included_sms,
                "voice_overage_rate": tariff.voice_overage_rate,
                "data_overage_rate": tariff.data_overage_rate,
                "sms_overage_rate": tariff.sms_overage_rate,
                "roaming_voice_rate": tariff.roaming_voice_rate,
                "roaming_data_rate": tariff.roaming_data_rate,
                "roaming_sms_rate": tariff.roaming_sms_rate,
                "lifecycle_status": "Active",
                "valid_from": add_months(AS_OF, -18),
                "valid_to": None,
            }
        )


def _add_treatment_plan(world: World, ids: IdFactory) -> None:
    plan_id = ids.uuid("treatment-plan", STANDARD_TREATMENT["code"])
    world.treatment_plan_id = plan_id
    world.rows["treatment_plans"].append({"id": plan_id, **STANDARD_TREATMENT})


def _add_incidents(world: World, ids: IdFactory) -> None:
    samples = (
        (
            "stuck_bill_run",
            "high",
            "open",
            "Synthetic bill run paused before invoice dispatch",
            "Example operations incident for a later phase. Rating finished; dispatch did not.",
            -3,
        ),
        (
            "rating_lag",
            "medium",
            "open",
            "Synthetic rating lag on the usage stream",
            "Example lag incident. The usage in this dataset is still on the synthetic clock.",
            -2,
        ),
        (
            "payment_batch_delay",
            "medium",
            "acknowledged",
            "Synthetic payment batch acknowledged late",
            "Example delay. Posted payments are consistent unless a planted fault says otherwise.",
            -1,
        ),
    )
    for key, severity, status, title, description, day_offset in samples:
        world.rows["incidents"].append(
            {
                "id": ids.uuid("incident", key),
                "incident_type": key,
                "severity": severity,
                "status": status,
                "title": title,
                "description": description,
                "detected_at": at_noon(shift(AS_OF, day_offset)),
                "related_entity_type": None,
                "related_entity_id": None,
            }
        )


def _build_standard(
    world: World,
    ids: IdFactory,
    rng: random.Random,
    index: int,
    given: str,
    family: str,
    city: str,
    state: str,
    anomaly: str | None,
    config: GeneratorConfig,
    delinquent: bool,
) -> Bundle:
    cycle_day = 1 if index == 0 or anomaly else 1 + rng.randrange(28)
    periods = completed_periods(cycle_day, config.months)
    opened = at_noon(periods[0][0])
    ended = None
    status = "active"
    if anomaly == "feature_active_after_cancellation":
        ended = at_noon(periods[-1][0])
        status = "cancelled"
    discount = _discount(rng, anomaly)
    tariff = _tariff_for(index, anomaly)
    bundle = open_account(
        world,
        ids,
        index,
        given,
        family,
        city,
        state,
        world.plan_ids[tariff.code],
        tariff,
        opened,
        cycle_day,
        discount,
        status,
        ended,
    )
    bundle.periods = periods
    overrides = {"data": Decimal("100")} if anomaly in SMALL_DATA else {}
    _add_plan_entitlements(bundle, periods, overrides)
    if anomaly is None:
        _maybe_optional_products(bundle, rng, periods)
    _bill_periods(bundle, periods, anomaly, config, delinquent, rng)
    if delinquent:
        _apply_healthy_treatment(bundle)
    return bundle


def _discount(rng: random.Random, anomaly: str | None) -> Decimal:
    if anomaly == "missed_discount":
        return Decimal("10.00")
    if anomaly is None and rng.random() < 0.2:
        return Decimal("10.00")
    return ZERO


def _tariff_for(index: int, anomaly: str | None):
    if anomaly in SMALL_DATA | {"overage_on_covered_usage", "allowance_not_reset"}:
        return TARIFFS_BY_CODE["ULTRA-999"]
    if anomaly in {"roaming_spike", "charge_after_cancellation", "sim_swap"}:
        return TARIFFS_BY_CODE["MAX-599"]
    return TARIFFS[index % len(TARIFFS)]


def _add_plan_entitlements(bundle: Bundle, periods, overrides: dict) -> None:
    ended = bundle.subscription["ended_at"]
    for feature, unit, attr in DOMESTIC_FEATURES:
        allowance = overrides.get(feature, Decimal(getattr(bundle.tariff, attr)))
        entitlement = add_entitlement(
            bundle,
            "plan",
            bundle.tariff.code,
            feature,
            allowance,
            unit,
            "active" if ended is None else "cancelled",
            bundle.subscription["started_at"],
            ended,
            True,
            (feature, "plan"),
        )
        if ended is not None:
            entitlement["status"] = "cancelled"
        for period_index, period in enumerate(periods):
            if ended is not None and at_noon(period[0]) >= ended:
                continue
            add_balance(
                bundle,
                entitlement,
                period,
                allowance,
                at_noon(period[0]),
                (feature, period_index),
            )


def _maybe_optional_products(bundle: Bundle, rng: random.Random, periods) -> None:
    opened = bundle.subscription["started_at"]
    if rng.random() < 0.30:
        add_vas(bundle, _caller_tune(), opened, True, "active", ("caller",))
    if rng.random() < 0.12:
        add_vas(bundle, _ott(), opened, True, "active", ("ott",))
    if rng.random() < 0.10:
        pack = add_pack(bundle, ROAM_ASIA, at_noon(periods[0][0]) + timedelta(days=2), ROAM_ASIA["days"], ("asia",))
        entitlement = add_entitlement(
            bundle,
            "roaming_pack",
            str(pack["id"]),
            "roaming_data",
            Decimal(pack["data_mb"]),
            "MB",
            "active",
            pack["valid_from"],
            pack["valid_to"],
            False,
            ("roam-asia",),
        )
        add_balance(
            bundle,
            entitlement,
            (pack["valid_from"].date(), pack["valid_to"].date() + timedelta(days=1)),
            Decimal(pack["data_mb"]),
            pack["valid_from"],
            ("roam-asia-bal",),
        )


def _caller_tune():
    from billpilot.synthetic.catalog import CALLER_TUNE

    return CALLER_TUNE


def _ott():
    from billpilot.synthetic.catalog import OTT_MINI

    return OTT_MINI


def _bill_periods(bundle, periods, anomaly, config, delinquent, rng) -> None:
    unpaid_index = len(periods) - 2 if delinquent else None
    last_index = len(periods) - 1
    for period_index, period in enumerate(periods):
        start, _end = period
        ended = bundle.subscription["ended_at"]
        if ended is not None and ended <= at_noon(start):
            continue
        _add_period_usage(bundle, period, period_index, anomaly, config, rng)
        invoice = _make_invoice(bundle, period, period_index)
        pay = period_index != unpaid_index and not (anomaly in PAYMENT_FAULTS and period_index == last_index)
        if pay:
            _add_posted_payment(bundle, invoice, period_index, METHODS[(bundle.index + period_index) % len(METHODS)])
        else:
            if invoice["due_date"] < AS_OF:
                _add_late_fee(bundle, invoice)
            invoice["amount_due"] = invoice["total"]
            invoice["status"] = "issued"


def _add_late_fee(bundle: Bundle, invoice: dict) -> None:
    add_line(
        bundle,
        invoice,
        charge_type="late_fee",
        description="Late fee",
        qty=Decimal("1"),
        unit_price=LATE_FEE,
        amount=LATE_FEE,
        key=("late-fee", invoice["id"]),
    )
    recompute_invoice(bundle, invoice)


def _add_period_usage(bundle, period, period_index, anomaly, config, rng) -> None:
    start, end = period
    ended = bundle.subscription["ended_at"]
    if anomaly is None:
        specs = []
        for nth in range(config.voice_events_per_period):
            specs.append(("voice", Decimal(1 + rng.randrange(20)), "on-net", None, nth))
        for nth in range(config.data_events_per_period):
            specs.append(("data", Decimal(40 + rng.randrange(360)), None, None, nth))
        for nth in range(config.sms_events_per_period):
            specs.append(("sms", Decimal(1 + rng.randrange(5)), "on-net", None, nth))
        if rng.random() < 0.15:
            specs.append(
                (
                    "roaming_data",
                    Decimal(20 + rng.randrange(60)),
                    None,
                    ROAMING_COUNTRIES[rng.randrange(len(ROAMING_COUNTRIES))],
                    0,
                )
            )
    else:
        specs = [
            ("voice", Decimal("10"), "on-net", None, 0),
            ("voice", Decimal("15"), "on-net", None, 1),
            ("data", Decimal("80"), None, None, 0),
            ("data", Decimal("80"), None, None, 1),
            ("sms", Decimal("2"), "on-net", None, 0),
        ]
    usable_days = max((end - start).days - 1, 1)
    for nth, (event_type, qty, destination, country, slot) in enumerate(specs):
        day = min(2 + slot * 3 + nth, usable_days)
        when = stamp(start, day)
        if ended is not None and when >= ended:
            continue
        add_usage(
            bundle,
            event_type,
            when,
            qty,
            period,
            destination,
            country,
            (period_index, event_type, slot, nth),
        )


def _make_invoice(bundle: Bundle, period, period_index: int) -> dict:
    start, end = period
    invoice = {
        "id": bundle.ids.uuid("invoice", bundle.index, period_index),
        "account_id": bundle.account["id"],
        "bill_number": f"INV-{bundle.index + 1:06d}-{period_index + 1:02d}",
        "period_start": start,
        "period_end": end,
        "issue_date": end,
        "due_date": shift(end, 15),
        "status": "issued",
        "subtotal": ZERO,
        "tax": ZERO,
        "total": ZERO,
        "amount_due": ZERO,
        "currency": "INR",
        "created_at": at_noon(end),
    }
    bundle.invoices.append(invoice)
    fee = _rental_fee(bundle, start, end)
    if fee > 0:
        add_line(
            bundle,
            invoice,
            charge_type="recurring",
            description=f"Monthly rental {bundle.tariff.name}",
            qty=Decimal("1"),
            unit_price=fee,
            amount=fee,
            tariff_plan_id=bundle.subscription["tariff_plan_id"],
            key=("rental", period_index),
        )
        percent = Decimal(bundle.subscription["discount_percent"])
        if percent > 0:
            discount_amount = money(fee * percent / Decimal("100"))
            add_line(
                bundle,
                invoice,
                charge_type="discount",
                description=f"Loyalty discount {percent:.0f}%",
                qty=Decimal("1"),
                unit_price=discount_amount,
                amount=-discount_amount,
                tariff_plan_id=bundle.subscription["tariff_plan_id"],
                key=("discount", period_index),
            )
    for vas in bundle.vas:
        if not vas["opted_in"] or vas["status"] != "active":
            continue
        if vas["ended_at"] is not None and vas["ended_at"] <= at_noon(start):
            continue
        add_line(
            bundle,
            invoice,
            charge_type="vas",
            description=vas["name"],
            qty=Decimal("1"),
            unit_price=vas["monthly_fee"],
            amount=vas["monthly_fee"],
            key=("vas", vas["product_code"], period_index),
        )
    for pack in bundle.packs:
        if start <= pack["valid_from"].date() < end:
            add_line(
                bundle,
                invoice,
                charge_type="addon",
                description=pack["name"],
                qty=Decimal("1"),
                unit_price=pack["price"],
                amount=pack["price"],
                key=("pack", pack["pack_code"], period_index),
            )
    descriptions = {
        "voice": "Voice overage",
        "data": "Data overage",
        "sms": "SMS overage",
        "roaming_voice": "Roaming voice",
        "roaming_data": "Roaming data",
        "roaming_sms": "Roaming SMS",
    }
    for event in bundle.events:
        if event["period_start"] != start:
            continue
        event["billed"] = True
        if event["rated_amount"] <= 0:
            continue
        charge_type = "roaming" if event["event_type"].startswith("roaming") else "usage"
        overage_qty = quantity(Decimal(event["rated_amount"]) / Decimal(event["rate_applied"]))
        amount = money(overage_qty * Decimal(event["rate_applied"]))
        event["rated_amount"] = amount
        add_line(
            bundle,
            invoice,
            charge_type=charge_type,
            description=descriptions[event["event_type"]],
            qty=overage_qty,
            unit_price=event["rate_applied"],
            amount=amount,
            usage_event_id=event["id"],
            tariff_plan_id=bundle.subscription["tariff_plan_id"],
            key=("usage", event["id"]),
        )
    recompute_invoice(bundle, invoice)
    return invoice


def _rental_fee(bundle: Bundle, start, end) -> Decimal:
    fee = bundle.tariff.monthly_fee
    ended = bundle.subscription["ended_at"]
    if ended is None or not (start <= ended.date() < end):
        return money(fee)
    total_days = (end - start).days
    used_days = max(0, min(total_days, (ended.date() - start).days))
    if used_days == 0 or total_days == 0:
        return ZERO
    return money(fee * Decimal(used_days) / Decimal(total_days))


def _add_posted_payment(bundle: Bundle, invoice: dict, period_index: int, method: str) -> None:
    received = at_noon(shift(invoice["issue_date"], 2))
    payment_id = bundle.ids.uuid("payment", bundle.index, period_index)
    bundle.payments.append(
        {
            "id": payment_id,
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_number": f"PAY-{bundle.index + 1:06d}-{period_index + 1:02d}",
            "amount": invoice["total"],
            "method": method,
            "status": "posted",
            "reference": f"REF-{bundle.index + 1:06d}-{period_index + 1:02d}",
            "received_at": received,
            "posted_at": received,
            "currency": "INR",
            "created_at": received,
        }
    )
    bundle.attempts.append(
        {
            "id": bundle.ids.uuid("attempt", bundle.index, period_index, 1),
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_id": payment_id,
            "attempt_number": 1,
            "amount": invoice["total"],
            "method": method,
            "status": "succeeded",
            "failure_reason": None,
            "attempted_at": received,
        }
    )
    invoice["amount_due"] = ZERO
    invoice["status"] = "paid"


def _apply_healthy_treatment(bundle: Bundle) -> None:
    invoice = next(row for row in bundle.invoices if row["amount_due"] > 0)
    plan = TreatmentThresholds(
        STANDARD_TREATMENT["reminder_after_days"],
        STANDARD_TREATMENT["soft_bar_after_days"],
        STANDARD_TREATMENT["hard_bar_after_days"],
        STANDARD_TREATMENT["disconnect_after_days"],
    )
    days = (AS_OF - invoice["due_date"]).days
    stage = stage_for_days(days, plan)
    if stage is None:
        return
    started = at_noon(shift(invoice["due_date"], threshold_days(stage, plan)))
    treatment = add_treatment(bundle, stage, "active", started, None, ("healthy",))
    for reached in stages_reached(days, plan):
        occurred = at_noon(shift(invoice["due_date"], threshold_days(reached, plan)))
        add_dunning(
            bundle,
            treatment,
            reached,
            occurred,
            f"Correct {reached.replace('_', ' ')} for an unpaid bill.",
            (reached,),
        )


def usage_quantity_in_period(bundle: Bundle, feature: str, period_start) -> Decimal:
    total = ZERO
    for event in bundle.events:
        if event["event_type"] == feature and event["period_start"] == period_start:
            total += Decimal(event["quantity"])
    return quantity(total)
