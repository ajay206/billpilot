"""The billing rules are small enough to recompute by hand."""

from datetime import date
from decimal import Decimal

import pytest

from billpilot.billing import (
    AS_OF,
    TreatmentThresholds,
    completed_periods,
    credit_for_removing,
    gst,
    money,
    stage_for_days,
    stages_reached,
)
from billpilot.synthetic.catalog import STANDARD_TREATMENT


def test_gst_is_eighteen_percent():
    assert gst(Decimal("100")) == Decimal("18.00")
    assert gst(Decimal("199")) == Decimal("35.82")
    assert gst(Decimal("0")) == Decimal("0.00")
    assert gst(Decimal("-5")) == Decimal("0.00")


def test_credit_includes_gst_on_the_removed_amount():
    # A 100.00 charge inside a larger bill, plus 18% GST, is a 118.00 credit.
    subtotal = Decimal("100.00")
    total = money(subtotal + gst(subtotal))
    assert credit_for_removing(subtotal, total, Decimal("100.00")) == Decimal("118.00")


def test_six_completed_cycles_end_on_or_before_the_synthetic_clock():
    periods = completed_periods(1, 6, AS_OF)
    assert len(periods) == 6
    assert periods[-1][1] <= AS_OF
    assert periods[0][1] == periods[1][0]
    assert all(end > start for start, end in periods)


def test_cycle_day_after_the_clock_uses_the_previous_month():
    # 4 October is before the 15th, so the newest completed cycle ended 15 September.
    periods = completed_periods(15, 1, date(2026, 10, 4))
    assert periods == [(date(2026, 8, 15), date(2026, 9, 15))]


def test_treatment_ladder_thresholds_match_the_catalogue():
    plan = TreatmentThresholds(
        STANDARD_TREATMENT["reminder_after_days"],
        STANDARD_TREATMENT["soft_bar_after_days"],
        STANDARD_TREATMENT["hard_bar_after_days"],
        STANDARD_TREATMENT["disconnect_after_days"],
    )
    assert plan.reminder_after_days == 3
    assert plan.soft_bar_after_days == 10
    assert plan.hard_bar_after_days == 20
    assert plan.disconnect_after_days == 45
    assert stage_for_days(2, plan) is None
    assert stage_for_days(3, plan) == "reminder"
    assert stage_for_days(10, plan) == "soft_bar"
    assert stage_for_days(25, plan) == "hard_bar"
    assert stage_for_days(45, plan) == "disconnect"
    assert stages_reached(25, plan) == ["reminder", "soft_bar", "hard_bar"]


def test_months_below_two_are_rejected():
    from billpilot.synthetic.config import GeneratorConfig

    with pytest.raises(ValueError):
        GeneratorConfig(months=1, customer_count=500).validate()
