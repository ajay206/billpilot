"""Treatment faults, and a few healthy control accounts that follow the ladder correctly.

Dates are relative to the synthetic clock so a test can recompute the stage from
the due date and the plan thresholds.
"""

from datetime import timedelta
from decimal import Decimal

from billpilot.billing import (
    AS_OF,
    ZERO,
    TreatmentThresholds,
    add_months,
    at_noon,
    shift,
    stage_for_days,
    stages_reached,
    threshold_days,
)
from billpilot.synthetic.catalog import DOMESTIC_FEATURES, STANDARD_TREATMENT, TARIFFS_BY_CODE
from billpilot.synthetic.records import (
    add_balance,
    add_dispute,
    add_dunning,
    add_entitlement,
    add_line,
    add_ticket,
    add_treatment,
    anomaly_record,
    control_record,
    open_account,
    recompute_invoice,
)

THRESHOLDS = TreatmentThresholds(
    STANDARD_TREATMENT["reminder_after_days"],
    STANDARD_TREATMENT["soft_bar_after_days"],
    STANDARD_TREATMENT["hard_bar_after_days"],
    STANDARD_TREATMENT["disconnect_after_days"],
)


def build_treatment_anomaly(world, ids, index, given, family, city, state, anomaly):
    anomaly_type, sequence = anomaly
    bundle = _shell(world, ids, index, given, family, city, state)
    record = {
        "barred_after_paying": _barred_after_paying,
        "treated_during_open_dispute": _treated_during_dispute,
        "payment_not_ending_treatment": _payment_not_ending,
        "promise_to_pay_ignored": _promise_ignored,
        "exempt_account_treated": _exempt_treated,
    }[anomaly_type](bundle, sequence)
    bundle.flush()
    return record


def build_control(world, ids, index, given, family, city, state, control_type):
    bundle = _shell(world, ids, index, given, family, city, state)
    record = {
        "unpaid_treated": _control_unpaid,
        "exempt_respected": _control_exempt,
        "dispute_held": _control_dispute,
        "promise_honored": _control_promise,
        "failed_autopay_recovered": _control_failed_autopay,
    }[control_type](bundle)
    bundle.flush()
    return record


def _shell(world, ids, index, given, family, city, state):
    tariff = TARIFFS_BY_CODE["MAX-599"]
    opened = at_noon(shift(AS_OF, -180))
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
        1,
        ZERO,
    )
    period = (shift(AS_OF, -70), shift(AS_OF, -40))
    for feature, unit, attr in DOMESTIC_FEATURES:
        allowance = Decimal(getattr(tariff, attr))
        entitlement = add_entitlement(
            bundle,
            "plan",
            tariff.code,
            feature,
            allowance,
            unit,
            "active",
            opened,
            None,
            True,
            (feature, "plan"),
        )
        add_balance(bundle, entitlement, period, allowance, at_noon(period[0]), (feature, "case"))
    return bundle


def _invoice(bundle, issue, due):
    start = add_months(issue, -1)
    invoice = {
        "id": bundle.ids.uuid("invoice", bundle.index, "case"),
        "account_id": bundle.account["id"],
        "bill_number": f"INV-{bundle.index + 1:06d}-01",
        "period_start": start,
        "period_end": issue,
        "issue_date": issue,
        "due_date": due,
        "status": "issued",
        "subtotal": ZERO,
        "tax": ZERO,
        "total": ZERO,
        "amount_due": ZERO,
        "currency": "INR",
        "created_at": at_noon(issue),
    }
    bundle.invoices.append(invoice)
    fee = bundle.tariff.monthly_fee
    add_line(
        bundle,
        invoice,
        charge_type="recurring",
        description=f"Monthly rental {bundle.tariff.name}",
        qty=Decimal("1"),
        unit_price=fee,
        amount=fee,
        tariff_plan_id=bundle.subscription["tariff_plan_id"],
        key=("rental", "case"),
    )
    recompute_invoice(bundle, invoice)
    invoice["amount_due"] = invoice["total"]
    invoice["status"] = "issued"
    return invoice


def _pay(bundle, invoice, when, suffix):
    payment_id = bundle.ids.uuid("payment", bundle.index, suffix)
    bundle.payments.append(
        {
            "id": payment_id,
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_number": f"PAY-{bundle.index + 1:06d}-{suffix}",
            "amount": invoice["total"],
            "method": "upi",
            "status": "posted",
            "reference": f"REF-{bundle.index + 1:06d}-{suffix}",
            "received_at": when,
            "posted_at": when,
            "currency": "INR",
            "created_at": when,
        }
    )
    bundle.attempts.append(
        {
            "id": bundle.ids.uuid("attempt", bundle.index, suffix),
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_id": payment_id,
            "attempt_number": 1,
            "amount": invoice["total"],
            "method": "upi",
            "status": "succeeded",
            "failure_reason": None,
            "attempted_at": when,
        }
    )
    invoice["amount_due"] = ZERO
    invoice["status"] = "paid"
    return payment_id


def _fail(bundle, invoice, when, attempt_number: int = 1, reason: str = "insufficient_funds"):
    bundle.attempts.append(
        {
            "id": bundle.ids.uuid("attempt", bundle.index, "failed", attempt_number),
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_id": None,
            "attempt_number": attempt_number,
            "amount": invoice["total"],
            "method": "autopay",
            "status": "failed",
            "failure_reason": reason,
            "attempted_at": when,
        }
    )


def _ladder(bundle, invoice):
    days = (AS_OF - invoice["due_date"]).days
    stage = stage_for_days(days, THRESHOLDS)
    started = at_noon(shift(invoice["due_date"], threshold_days(stage, THRESHOLDS)))
    treatment = add_treatment(bundle, stage, "active", started, None, ("ladder",))
    for reached in stages_reached(days, THRESHOLDS):
        occurred = at_noon(shift(invoice["due_date"], threshold_days(reached, THRESHOLDS)))
        add_dunning(
            bundle,
            treatment,
            reached,
            occurred,
            f"Correct {reached.replace('_', ' ')} on an unpaid bill.",
            (reached,),
        )
    return treatment


def _barred_after_paying(bundle, sequence):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    paid_at = at_noon(shift(AS_OF, -30))
    payment_id = _pay(bundle, invoice, paid_at, "PAID")
    barred_at = at_noon(shift(AS_OF, -5))
    treatment = add_treatment(bundle, "soft_bar", "active", barred_at, None, ("barred",))
    add_dunning(bundle, treatment, "soft_bar", barred_at, "Bar applied after the bill was already paid.", ("bar",))
    return anomaly_record(
        bundle,
        "barred_after_paying",
        sequence,
        "The account was soft-barred after a payment had already cleared the bill.",
        "Remove the bar. A paid account should not be treated for that bill.",
        None,
        invoice,
        {"payment_id": str(payment_id), "account_treatment_id": str(treatment["id"])},
    )


def _treated_during_dispute(bundle, sequence):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    _fail(bundle, invoice, at_noon(shift(AS_OF, -24)))
    opened = at_noon(shift(AS_OF, -20))
    ticket = add_ticket(
        bundle,
        "Billing dispute open",
        "Customer disputes the latest bill. Treatment should be on hold.",
        opened,
        "dispute",
        ("dispute",),
    )
    dispute = add_dispute(
        bundle,
        invoice,
        ticket,
        "billing",
        "Open dispute. Collections should not bar this account while it is open.",
        opened,
        ("dispute",),
    )
    barred_at = at_noon(shift(AS_OF, -5))
    treatment = add_treatment(bundle, "soft_bar", "active", barred_at, None, ("barred",))
    add_dunning(
        bundle,
        treatment,
        "soft_bar",
        barred_at,
        "Bar applied while a dispute was already open.",
        ("bar",),
    )
    return anomaly_record(
        bundle,
        "treated_during_open_dispute",
        sequence,
        "A soft bar was applied while a billing dispute was still open.",
        "Hold treatment until the dispute is resolved, and remove the bar.",
        None,
        invoice,
        {
            "dispute_id": str(dispute["id"]),
            "ticket_id": str(ticket["id"]),
            "account_treatment_id": str(treatment["id"]),
        },
    )


def _payment_not_ending(bundle, sequence):
    invoice = _invoice(bundle, shift(AS_OF, -45), shift(AS_OF, -30))
    barred_at = at_noon(shift(invoice["due_date"], 10))
    treatment = add_treatment(bundle, "soft_bar", "active", barred_at, None, ("barred",))
    add_dunning(bundle, treatment, "soft_bar", barred_at, "Soft bar while the bill was unpaid.", ("bar",))
    paid_at = at_noon(shift(AS_OF, -2))
    payment_id = _pay(bundle, invoice, paid_at, "LATE")
    return anomaly_record(
        bundle,
        "payment_not_ending_treatment",
        sequence,
        "The bill was paid in full after the bar, but treatment is still active.",
        "Posting the payment should have ended treatment and removed the bar.",
        None,
        invoice,
        {"payment_id": str(payment_id), "account_treatment_id": str(treatment["id"])},
    )


def _promise_ignored(bundle, sequence):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    _fail(bundle, invoice, at_noon(shift(AS_OF, -20)))
    promised_at = at_noon(shift(AS_OF, -10))
    promise_by = at_noon(shift(AS_OF, 10))
    treatment = add_treatment(bundle, "hard_bar", "active", at_noon(shift(AS_OF, -3)), None, ("ignored",))
    add_dunning(
        bundle,
        treatment,
        "promise_to_pay",
        promised_at,
        "Customer promised to pay.",
        ("promise",),
        promise_pay_by=promise_by,
        promise_amount=invoice["total"],
    )
    add_dunning(
        bundle,
        treatment,
        "hard_bar",
        at_noon(shift(AS_OF, -3)),
        "Hard bar applied before the promise-to-pay date.",
        ("bar",),
    )
    return anomaly_record(
        bundle,
        "promise_to_pay_ignored",
        sequence,
        "A hard bar was applied before the promise-to-pay date.",
        "Honour the promise and remove the bar until the promised date.",
        None,
        invoice,
        {"account_treatment_id": str(treatment["id"])},
    )


def _exempt_treated(bundle, sequence):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    _fail(bundle, invoice, at_noon(shift(AS_OF, -20)))
    exemption = {
        "id": bundle.ids.uuid("exemption", bundle.index, "hardship"),
        "account_id": bundle.account["id"],
        "reason": "Synthetic hardship exemption",
        "valid_from": at_noon(shift(AS_OF, -60)),
        "valid_to": at_noon(shift(AS_OF, 30)),
        "created_by": "ops-demo",
    }
    bundle.exemptions.append(exemption)
    barred_at = at_noon(shift(AS_OF, -5))
    treatment = add_treatment(bundle, "soft_bar", "active", barred_at, None, ("barred",))
    add_dunning(
        bundle,
        treatment,
        "soft_bar",
        barred_at,
        "Bar applied inside an exemption window.",
        ("bar",),
    )
    return anomaly_record(
        bundle,
        "exempt_account_treated",
        sequence,
        "The account was barred inside an active treatment exemption.",
        "Remove the bar. An exempt account must not be treated in the exemption window.",
        None,
        invoice,
        {"exemption_id": str(exemption["id"]), "account_treatment_id": str(treatment["id"])},
    )


def _control_unpaid(bundle):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    _fail(bundle, invoice, at_noon(shift(AS_OF, -24)))
    treatment = _ladder(bundle, invoice)
    return control_record(
        bundle,
        "unpaid_treated",
        "Unpaid bill is on the correct ladder stage for its due date. This is not a planted fault.",
        invoice,
        {"account_treatment_id": str(treatment["id"])},
    )


def _control_exempt(bundle):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    exemption = {
        "id": bundle.ids.uuid("exemption", bundle.index, "respected"),
        "account_id": bundle.account["id"],
        "reason": "Synthetic exemption that was respected",
        "valid_from": at_noon(shift(AS_OF, -60)),
        "valid_to": at_noon(shift(AS_OF, 30)),
        "created_by": "ops-demo",
    }
    bundle.exemptions.append(exemption)
    return control_record(
        bundle,
        "exempt_respected",
        "The account is unpaid and exempt, and it was not barred.",
        invoice,
        {"exemption_id": str(exemption["id"])},
    )


def _control_dispute(bundle):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    opened = at_noon(shift(AS_OF, -40))
    ticket = add_ticket(
        bundle,
        "Dispute holding treatment",
        "Open dispute correctly holds the collections ladder.",
        opened,
        "dispute",
        ("hold",),
    )
    dispute = add_dispute(
        bundle,
        invoice,
        ticket,
        "billing",
        "Open dispute. Treatment is held and no bar was applied.",
        opened,
        ("hold",),
    )
    treatment = add_treatment(bundle, "reminder", "held", opened, "open_dispute", ("held",))
    return control_record(
        bundle,
        "dispute_held",
        "An open dispute is holding treatment. No bar was applied.",
        invoice,
        {"dispute_id": str(dispute["id"]), "account_treatment_id": str(treatment["id"])},
    )


def _control_promise(bundle):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    reminded = at_noon(shift(invoice["due_date"], THRESHOLDS.reminder_after_days))
    promise_by = at_noon(shift(AS_OF, 14))
    treatment = add_treatment(bundle, "reminder", "active", reminded, None, ("promise",))
    add_dunning(bundle, treatment, "reminder", reminded, "Reminder sent.", ("reminder",))
    add_dunning(
        bundle,
        treatment,
        "promise_to_pay",
        reminded + timedelta(hours=1),
        "Promise recorded. No bar until the promised date.",
        ("promise",),
        promise_pay_by=promise_by,
        promise_amount=invoice["total"],
    )
    return control_record(
        bundle,
        "promise_honored",
        "A promise to pay is still in force, so the account was not barred.",
        invoice,
        {"account_treatment_id": str(treatment["id"])},
    )


def _control_failed_autopay(bundle):
    invoice = _invoice(bundle, shift(AS_OF, -40), shift(AS_OF, -25))
    _fail(bundle, invoice, at_noon(shift(AS_OF, -23)), attempt_number=1)
    paid_at = at_noon(shift(AS_OF, -20))
    payment_id = bundle.ids.uuid("payment", bundle.index, "recovered")
    bundle.payments.append(
        {
            "id": payment_id,
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_number": f"PAY-{bundle.index + 1:06d}-REC",
            "amount": invoice["total"],
            "method": "upi",
            "status": "posted",
            "reference": f"REF-{bundle.index + 1:06d}-REC",
            "received_at": paid_at,
            "posted_at": paid_at,
            "currency": "INR",
            "created_at": paid_at,
        }
    )
    bundle.attempts.append(
        {
            "id": bundle.ids.uuid("attempt", bundle.index, "recovered"),
            "account_id": bundle.account["id"],
            "invoice_id": invoice["id"],
            "payment_id": payment_id,
            "attempt_number": 2,
            "amount": invoice["total"],
            "method": "upi",
            "status": "succeeded",
            "failure_reason": None,
            "attempted_at": paid_at,
        }
    )
    invoice["amount_due"] = ZERO
    invoice["status"] = "paid"
    return control_record(
        bundle,
        "failed_autopay_recovered",
        "The first autopay failed and a later payment was posted. The bill is settled.",
        invoice,
        {"payment_id": str(payment_id)},
    )
