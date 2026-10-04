"""Small billing rules shared by the generator and the tests.

These are simplified synthetic rules, written down in one place so a bill can be
recomputed by hand: one GST rate, a four-step treatment ladder, and a fixed clock.
"""

import calendar
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# The generator never reads the wall clock. Every seeded timestamp is derived from this date.
AS_OF = date(2026, 10, 1)
GST_RATE = Decimal("0.18")
MONEY = Decimal("0.01")
QTY = Decimal("0.001")
ZERO = Decimal("0.00")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def rate(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def credit_for_removing(subtotal: Decimal, total: Decimal, pre_tax_amount: Decimal) -> Decimal:
    """How much of a bill is explained by one pre-tax amount, including the GST on it."""
    correct_subtotal = money(subtotal - pre_tax_amount)
    correct_total = money(correct_subtotal + gst(correct_subtotal))
    return money(total - correct_total)


def quantity(value: Decimal) -> Decimal:
    return value.quantize(QTY, rounding=ROUND_HALF_UP)


def gst(subtotal: Decimal) -> Decimal:
    """Indian telecom GST as a single 18% line. Non-positive subtotals are not taxed."""
    if subtotal <= 0:
        return ZERO
    return money(subtotal * GST_RATE)


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def at_noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)


def completed_periods(cycle_day: int, months: int, as_of: date = AS_OF) -> list[tuple[date, date]]:
    """Return `months` bill cycles whose end date is on or before `as_of`.

    A cycle ends on `cycle_day`. The newest end is the latest such date that is
    not after the synthetic clock, and each earlier cycle ends one month before.
    """
    year, month = as_of.year, as_of.month
    if as_of.day < cycle_day:
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    latest_end = date(year, month, cycle_day)
    periods: list[tuple[date, date]] = []
    for offset in range(months - 1, -1, -1):
        period_end = add_months(latest_end, -offset)
        period_start = add_months(period_end, -1)
        periods.append((period_start, period_end))
    return periods


class TreatmentThresholds:
    def __init__(
        self,
        reminder_after_days: int,
        soft_bar_after_days: int,
        hard_bar_after_days: int,
        disconnect_after_days: int,
    ) -> None:
        self.reminder_after_days = reminder_after_days
        self.soft_bar_after_days = soft_bar_after_days
        self.hard_bar_after_days = hard_bar_after_days
        self.disconnect_after_days = disconnect_after_days


def stage_for_days(days_past_due: int, plan: TreatmentThresholds) -> str | None:
    """Map days past due onto the ladder. None means the account is not due for treatment."""
    if days_past_due < plan.reminder_after_days:
        return None
    if days_past_due < plan.soft_bar_after_days:
        return "reminder"
    if days_past_due < plan.hard_bar_after_days:
        return "soft_bar"
    if days_past_due < plan.disconnect_after_days:
        return "hard_bar"
    return "disconnect"


def stages_reached(days_past_due: int, plan: TreatmentThresholds) -> list[str]:
    order = ("reminder", "soft_bar", "hard_bar", "disconnect")
    current = stage_for_days(days_past_due, plan)
    if current is None:
        return []
    return list(order[: order.index(current) + 1])


def threshold_days(stage: str, plan: TreatmentThresholds) -> int:
    return {
        "reminder": plan.reminder_after_days,
        "soft_bar": plan.soft_bar_after_days,
        "hard_bar": plan.hard_bar_after_days,
        "disconnect": plan.disconnect_after_days,
    }[stage]


def shift(day: date, days: int) -> date:
    return day + timedelta(days=days)
