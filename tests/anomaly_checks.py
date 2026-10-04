"""Confirm each planted fault is still visible in the stored rows.

The generator writes the answer key. These checks recompute the fault from the
tables, so a seed that only writes the label (and not the bad row) fails.
"""

from datetime import timedelta
from decimal import Decimal

from billpilot.billing import AS_OF, credit_for_removing
from billpilot.synthetic.catalog import PROMO_MONTHS, TARIFFS_BY_CODE


def _sid(value) -> str:
    return str(value)


def _index(rows: list[dict]) -> dict[str, dict]:
    return {_sid(row["id"]): row for row in rows}


def _dec(value) -> Decimal:
    return Decimal(str(value))


def check_anomaly(tables: dict[str, list[dict]], anomaly: dict) -> list[str]:
    kind = anomaly["type"]
    checker = CHECKERS[kind]
    try:
        checker(tables, anomaly)
    except AssertionError as exc:
        return [f"{anomaly['id']}: {exc}"]
    return []


def _invoice(tables, anomaly) -> dict:
    row = _index(tables["invoices"]).get(anomaly["invoice_id"])
    assert row is not None, "invoice from the answer key is missing"
    return row


def _lines(tables, invoice_id: str) -> list[dict]:
    return [row for row in tables["invoice_lines"] if _sid(row["invoice_id"]) == invoice_id]


def check_double_charge(tables, anomaly) -> None:
    invoice = _invoice(tables, anomaly)
    ids = anomaly["related_ids"]["invoice_line_ids"]
    lines = _index(tables["invoice_lines"])
    first, second = lines[ids[0]], lines[ids[1]]
    assert first["charge_type"] == second["charge_type"] == "recurring"
    assert first["amount"] == second["amount"]
    assert first["description"] == second["description"]
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], _dec(first["amount"]))
    assert credit == _dec(anomaly["expected_credit_inr"])


def check_roaming_spike(tables, anomaly) -> None:
    events = _index(tables["usage_events"])
    baseline_id, spike_id = anomaly["related_ids"]["usage_event_ids"]
    baseline, spike = events[baseline_id], events[spike_id]
    assert baseline["event_type"] == spike["event_type"] == "roaming_data"
    assert _dec(spike["quantity"]) > _dec(baseline["quantity"]) * 5
    flag = _index(tables["fraud_flags"])[anomaly["related_ids"]["fraud_flag_id"]]
    assert flag["flag_type"] == "roaming_spike" and flag["status"] == "open"


def check_wrong_rate(tables, anomaly) -> None:
    line = _index(tables["invoice_lines"])[anomaly["related_ids"]["invoice_line_id"]]
    subscription = _index(tables["subscriptions"])[anomaly["subscription_id"]]
    plan = _index(tables["tariff_plans"])[_sid(subscription["tariff_plan_id"])]
    catalogue = TARIFFS_BY_CODE[plan["code"]].data_overage_rate
    assert _dec(line["unit_price"]) == catalogue * 10
    invoice = _invoice(tables, anomaly)
    extra = _dec(line["amount"]) - (_dec(line["quantity"]) * catalogue)
    credit = credit_for_removing(invoice["subtotal"], invoice["total"], extra)
    assert credit == _dec(anomaly["expected_credit_inr"])


def check_missed_discount(tables, anomaly) -> None:
    subscription = _index(tables["subscriptions"])[anomaly["subscription_id"]]
    assert _dec(subscription["discount_percent"]) > 0
    kinds = {row["charge_type"] for row in _lines(tables, anomaly["invoice_id"])}
    assert "discount" not in kinds
    assert anomaly["expected_credit_inr"] is not None


def check_charge_after_cancellation(tables, anomaly) -> None:
    subscription = _index(tables["subscriptions"])[anomaly["subscription_id"]]
    event = _index(tables["usage_events"])[anomaly["related_ids"]["usage_event_id"]]
    assert subscription["status"] == "cancelled"
    assert event["started_at"] > subscription["ended_at"]
    assert anomaly["expected_credit_inr"] is not None


def check_vas_not_opted_in(tables, anomaly) -> None:
    vas = _index(tables["vas_subscriptions"])[anomaly["related_ids"]["vas_id"]]
    line = _index(tables["invoice_lines"])[anomaly["related_ids"]["invoice_line_id"]]
    assert vas["opted_in"] is False
    assert vas["product_code"] == "CALLER-TUNE"
    assert line["charge_type"] == "vas"
    assert _dec(line["amount"]) == _dec(vas["monthly_fee"])


def check_payment_not_recorded(tables, anomaly) -> None:
    invoice = _invoice(tables, anomaly)
    attempt = _index(tables["payment_attempts"])[anomaly["related_ids"]["payment_attempt_id"]]
    assert attempt["status"] == "succeeded"
    assert attempt["payment_id"] is None
    payments = [row for row in tables["payments"] if _sid(row["invoice_id"]) == anomaly["invoice_id"]]
    assert payments == []
    assert invoice["amount_due"] == invoice["total"]
    assert anomaly["expected_credit_inr"] is None


def check_payment_not_posted(tables, anomaly) -> None:
    invoice = _invoice(tables, anomaly)
    payment = _index(tables["payments"])[anomaly["related_ids"]["payment_id"]]
    assert payment["status"] == "received" and payment["posted_at"] is None
    assert invoice["amount_due"] == invoice["total"]
    assert anomaly["expected_credit_inr"] is None


def check_unbilled_usage(tables, anomaly) -> None:
    event = _index(tables["usage_events"])[anomaly["related_ids"]["usage_event_id"]]
    assert event["billed"] is False and event["rating_status"] == "unbilled"
    billed = [row for row in tables["invoice_lines"] if _sid(row.get("usage_event_id")) == _sid(event["id"])]
    assert billed == []
    assert _dec(anomaly["related_ids"]["unbilled_amount_inr"]) == _dec(event["rated_amount"])


def check_duplicate_usage(tables, anomaly) -> None:
    events = _index(tables["usage_events"])
    first_id, second_id = anomaly["related_ids"]["usage_event_ids"]
    first, second = events[first_id], events[second_id]
    assert first["source_event_id"] == second["source_event_id"] == anomaly["related_ids"]["source_event_id"]
    assert first["billed"] is True and second["billed"] is True
    assert second["rating_status"] == "duplicate"


def check_sim_swap(tables, anomaly) -> None:
    flag = _index(tables["fraud_flags"])[anomaly["related_ids"]["fraud_flag_id"]]
    assert flag["flag_type"] == "sim_swap" and flag["status"] == "open"
    events = _index(tables["usage_events"])
    burst = [events[event_id] for event_id in anomaly["related_ids"]["usage_event_ids"]]
    assert len(burst) >= 8
    started = min(row["started_at"] for row in burst)
    ended = max(row["started_at"] for row in burst)
    assert ended - started <= timedelta(hours=2)
    assert all(row["destination"] == "premium-rate" for row in burst)
    subscription = _index(tables["subscriptions"])[anomaly["subscription_id"]]
    assert subscription["sim_serial"] == flag["evidence"]["new_sim_serial"]
    assert subscription["sim_serial"] != flag["evidence"]["old_sim_serial"]


def _treatment(tables, anomaly) -> dict:
    return _index(tables["account_treatment"])[anomaly["related_ids"]["account_treatment_id"]]


def check_barred_after_paying(tables, anomaly) -> None:
    invoice = _invoice(tables, anomaly)
    payment = _index(tables["payments"])[anomaly["related_ids"]["payment_id"]]
    treatment = _treatment(tables, anomaly)
    assert payment["status"] == "posted" and invoice["amount_due"] == 0
    assert treatment["status"] == "active" and treatment["stage"] == "soft_bar"
    assert treatment["started_at"] > payment["posted_at"]


def check_treated_during_open_dispute(tables, anomaly) -> None:
    dispute = _index(tables["disputes"])[anomaly["related_ids"]["dispute_id"]]
    treatment = _treatment(tables, anomaly)
    assert dispute["status"] == "open"
    assert treatment["status"] == "active"
    assert treatment["started_at"] > dispute["opened_at"]


def check_payment_not_ending_treatment(tables, anomaly) -> None:
    invoice = _invoice(tables, anomaly)
    payment = _index(tables["payments"])[anomaly["related_ids"]["payment_id"]]
    treatment = _treatment(tables, anomaly)
    assert payment["status"] == "posted" and invoice["status"] == "paid"
    assert treatment["status"] == "active"
    assert payment["posted_at"] > treatment["started_at"]
    unbars = [
        row
        for row in tables["dunning_events"]
        if _sid(row["account_id"]) == anomaly["account_id"] and row["event_type"] == "unbar"
    ]
    assert unbars == []


def check_promise_to_pay_ignored(tables, anomaly) -> None:
    treatment = _treatment(tables, anomaly)
    events = [row for row in tables["dunning_events"] if _sid(row["account_treatment_id"]) == _sid(treatment["id"])]
    promise = next(row for row in events if row["event_type"] == "promise_to_pay")
    bar = next(row for row in events if row["event_type"] == "hard_bar")
    assert treatment["stage"] == "hard_bar" and treatment["status"] == "active"
    assert bar["occurred_at"] < promise["promise_pay_by"]


def check_exempt_account_treated(tables, anomaly) -> None:
    exemption = _index(tables["treatment_exemptions"])[anomaly["related_ids"]["exemption_id"]]
    treatment = _treatment(tables, anomaly)
    assert exemption["valid_from"] <= treatment["started_at"] <= exemption["valid_to"]
    assert treatment["status"] == "active" and treatment["stage"] == "soft_bar"


def check_addon_never_activated(tables, anomaly) -> None:
    entitlement = _index(tables["entitlements"])[anomaly["related_ids"]["entitlement_id"]]
    balances = [row for row in tables["entitlement_balances"] if _sid(row["entitlement_id"]) == _sid(entitlement["id"])]
    assert entitlement["status"] == "pending_activation"
    assert balances == []
    line = _index(tables["invoice_lines"])[anomaly["related_ids"]["invoice_line_id"]]
    assert _dec(line["amount"]) > 0


def check_allowance_not_reset(tables, anomaly) -> None:
    prior_id, latest_id = anomaly["related_ids"]["balance_ids"]
    balances = _index(tables["entitlement_balances"])
    prior, latest = balances[prior_id], balances[latest_id]
    assert latest["reset_at"] is None
    assert latest["consumed_quantity"] == prior["consumed_quantity"]
    assert latest["remaining_quantity"] == prior["remaining_quantity"]
    usage = sum(
        (
            _dec(row["quantity"])
            for row in tables["usage_events"]
            if row["event_type"] == "data"
            and row["period_start"] == latest["period_start"]
            and _sid(row["subscription_id"]) == anomaly["subscription_id"]
        ),
        Decimal("0"),
    )
    assert usage != _dec(latest["consumed_quantity"])


def _pack_grant(tables, anomaly) -> tuple[Decimal, Decimal, Decimal]:
    packs = _index(tables["roaming_packs"])
    first_id, second_id = anomaly["related_ids"]["roaming_pack_ids"]
    first, second = packs[first_id], packs[second_id]
    entitlement = _index(tables["entitlements"])[anomaly["related_ids"]["entitlement_id"]]
    return _dec(first["data_mb"]), _dec(second["data_mb"]), _dec(entitlement["allowance_quantity"])


def check_overlapping_double(tables, anomaly) -> None:
    first, second, granted = _pack_grant(tables, anomaly)
    assert granted == first + second


def check_overlapping_dropped(tables, anomaly) -> None:
    first, second, granted = _pack_grant(tables, anomaly)
    assert granted == first
    assert granted != first + second


def check_promo_ended_early(tables, anomaly) -> None:
    entitlement = _index(tables["entitlements"])[anomaly["related_ids"]["entitlement_id"]]
    assert entitlement["status"] == "expired"
    assert int(anomaly["related_ids"]["planned_months"]) == PROMO_MONTHS
    span_days = (entitlement["valid_to"] - entitlement["valid_from"]).days
    assert span_days < 40


def check_feature_active_after_cancellation(tables, anomaly) -> None:
    subscription = _index(tables["subscriptions"])[anomaly["subscription_id"]]
    vas = _index(tables["vas_subscriptions"])[anomaly["related_ids"]["vas_id"]]
    entitlement = _index(tables["entitlements"])[anomaly["related_ids"]["entitlement_id"]]
    assert subscription["status"] == "cancelled"
    assert vas["status"] == "cancelled"
    assert entitlement["status"] == "active"
    assert entitlement["feature_code"] == "ott_mini"


def check_overage_on_covered_usage(tables, anomaly) -> None:
    event = _index(tables["usage_events"])[anomaly["related_ids"]["usage_event_id"]]
    balance = _index(tables["entitlement_balances"])[anomaly["related_ids"]["balance_id"]]
    line = _index(tables["invoice_lines"])[anomaly["related_ids"]["invoice_line_id"]]
    assert _dec(event["rated_amount"]) > 0
    assert _dec(balance["remaining_quantity"]) >= _dec(event["quantity"])
    assert _dec(line["amount"]) == _dec(event["rated_amount"])


def check_controls(tables: dict[str, list[dict]], controls: list[dict]) -> list[str]:
    errors = []
    for control in controls:
        try:
            CONTROL_CHECKS[control["type"]](tables, control)
        except (AssertionError, KeyError, StopIteration) as exc:
            errors.append(f"{control['id']}: {exc}")
    return errors


def check_unpaid_treated(tables, control) -> None:
    invoice = _invoice(tables, control)
    treatment = _treatment(tables, control)
    assert invoice["amount_due"] == invoice["total"]
    assert treatment["status"] == "active" and treatment["stage"] == "hard_bar"


def check_exempt_respected(tables, control) -> None:
    exemption = _index(tables["treatment_exemptions"])[control["related_ids"]["exemption_id"]]
    assert exemption["valid_from"].date() <= AS_OF <= exemption["valid_to"].date()
    treatments = [row for row in tables["account_treatment"] if _sid(row["account_id"]) == control["account_id"]]
    assert treatments == []


def check_dispute_held(tables, control) -> None:
    dispute = _index(tables["disputes"])[control["related_ids"]["dispute_id"]]
    treatment = _treatment(tables, control)
    assert dispute["status"] == "open"
    assert treatment["status"] == "held" and treatment["hold_reason"] == "open_dispute"


def check_promise_honored(tables, control) -> None:
    treatment = _treatment(tables, control)
    events = [row for row in tables["dunning_events"] if _sid(row["account_treatment_id"]) == _sid(treatment["id"])]
    promise = next(row for row in events if row["event_type"] == "promise_to_pay")
    assert promise["promise_pay_by"].date() > AS_OF
    assert treatment["stage"] == "reminder"
    assert not any(row["event_type"] in {"soft_bar", "hard_bar"} for row in events)


def check_failed_autopay_recovered(tables, control) -> None:
    invoice = _invoice(tables, control)
    attempts = [row for row in tables["payment_attempts"] if _sid(row["invoice_id"]) == control["invoice_id"]]
    assert any(row["status"] == "failed" and row["attempt_number"] == 1 for row in attempts)
    payment = _index(tables["payments"])[control["related_ids"]["payment_id"]]
    assert payment["status"] == "posted"
    assert invoice["status"] == "paid" and invoice["amount_due"] == 0


CHECKERS = {
    "double_charge": check_double_charge,
    "roaming_spike": check_roaming_spike,
    "wrong_rate": check_wrong_rate,
    "missed_discount": check_missed_discount,
    "charge_after_cancellation": check_charge_after_cancellation,
    "vas_not_opted_in": check_vas_not_opted_in,
    "payment_not_recorded": check_payment_not_recorded,
    "payment_not_posted": check_payment_not_posted,
    "unbilled_usage": check_unbilled_usage,
    "duplicate_usage": check_duplicate_usage,
    "sim_swap": check_sim_swap,
    "barred_after_paying": check_barred_after_paying,
    "treated_during_open_dispute": check_treated_during_open_dispute,
    "payment_not_ending_treatment": check_payment_not_ending_treatment,
    "promise_to_pay_ignored": check_promise_to_pay_ignored,
    "exempt_account_treated": check_exempt_account_treated,
    "addon_never_activated": check_addon_never_activated,
    "allowance_not_reset": check_allowance_not_reset,
    "overlapping_packs_double_counted": check_overlapping_double,
    "overlapping_packs_dropped": check_overlapping_dropped,
    "promo_ended_early": check_promo_ended_early,
    "feature_active_after_cancellation": check_feature_active_after_cancellation,
    "overage_on_covered_usage": check_overage_on_covered_usage,
}

CONTROL_CHECKS = {
    "unpaid_treated": check_unpaid_treated,
    "exempt_respected": check_exempt_respected,
    "dispute_held": check_dispute_held,
    "promise_honored": check_promise_honored,
    "failed_autopay_recovered": check_failed_autopay_recovered,
}
