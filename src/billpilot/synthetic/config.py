"""Generator knobs. Anomaly counts are a dict so a demo can plant one of each or many."""

from dataclasses import dataclass, field

# Order is the order faults are assigned to customers, so it is part of the seed contract.
ANOMALY_TYPES: tuple[str, ...] = (
    "double_charge",
    "roaming_spike",
    "wrong_rate",
    "missed_discount",
    "charge_after_cancellation",
    "vas_not_opted_in",
    "payment_not_recorded",
    "payment_not_posted",
    "unbilled_usage",
    "duplicate_usage",
    "sim_swap",
    "barred_after_paying",
    "treated_during_open_dispute",
    "payment_not_ending_treatment",
    "promise_to_pay_ignored",
    "exempt_account_treated",
    "addon_never_activated",
    "allowance_not_reset",
    "overlapping_packs_double_counted",
    "overlapping_packs_dropped",
    "promo_ended_early",
    "feature_active_after_cancellation",
    "overage_on_covered_usage",
)

TREATMENT_ANOMALIES = frozenset(
    {
        "barred_after_paying",
        "treated_during_open_dispute",
        "payment_not_ending_treatment",
        "promise_to_pay_ignored",
        "exempt_account_treated",
    }
)

CONTROL_TYPES: tuple[str, ...] = (
    "unpaid_treated",
    "exempt_respected",
    "dispute_held",
    "promise_honored",
    "failed_autopay_recovered",
)

DEFAULT_ANOMALY_COUNTS: dict[str, int] = {
    "double_charge": 6,
    "roaming_spike": 4,
    "wrong_rate": 6,
    "missed_discount": 6,
    "charge_after_cancellation": 4,
    "vas_not_opted_in": 4,
    "payment_not_recorded": 4,
    "payment_not_posted": 4,
    "unbilled_usage": 6,
    "duplicate_usage": 6,
    "sim_swap": 3,
    "barred_after_paying": 3,
    "treated_during_open_dispute": 3,
    "payment_not_ending_treatment": 3,
    "promise_to_pay_ignored": 3,
    "exempt_account_treated": 3,
    "addon_never_activated": 4,
    "allowance_not_reset": 4,
    "overlapping_packs_double_counted": 3,
    "overlapping_packs_dropped": 3,
    "promo_ended_early": 3,
    "feature_active_after_cancellation": 3,
    "overage_on_covered_usage": 4,
}


def _copy_counts() -> dict[str, int]:
    return dict(DEFAULT_ANOMALY_COUNTS)


@dataclass
class GeneratorConfig:
    seed: int = 42
    customer_count: int = 500
    months: int = 6
    voice_events_per_period: int = 3
    data_events_per_period: int = 3
    sms_events_per_period: int = 1
    delinquent_count: int = 8
    anomaly_counts: dict[str, int] = field(default_factory=_copy_counts)

    def validate(self) -> None:
        unknown = set(self.anomaly_counts) - set(ANOMALY_TYPES)
        missing = set(ANOMALY_TYPES) - set(self.anomaly_counts)
        if unknown or missing:
            raise ValueError(
                f"anomaly_counts must name exactly the known types; unknown={sorted(unknown)} missing={sorted(missing)}"
            )
        if any(count < 0 for count in self.anomaly_counts.values()):
            raise ValueError("anomaly counts cannot be negative")
        if self.months < 2:
            raise ValueError("months must be at least 2 so bill cycles and resets can be compared")
        if self.customer_count < self.minimum_customers():
            raise ValueError(
                "customer_count is too small for the demo customer, every planted fault "
                f"and the healthy control accounts; need at least {self.minimum_customers()}"
            )

    def minimum_customers(self) -> int:
        """Demo customer at index 0, then one index per fault, then control accounts on even indexes."""
        cursor = 1 + sum(self.anomaly_counts.values())
        for _ in CONTROL_TYPES:
            if cursor % 2 == 1:
                cursor += 1
            cursor += 2
        return cursor + self.delinquent_count


def small_config() -> GeneratorConfig:
    """One of every fault, two bill cycles. Used by tests and quick dry-runs."""
    return GeneratorConfig(
        customer_count=48,
        months=2,
        voice_events_per_period=2,
        data_events_per_period=2,
        sms_events_per_period=1,
        delinquent_count=0,
        anomaly_counts={name: 1 for name in ANOMALY_TYPES},
    )
