"""The 23 tables in the Phase 1 billing model, grouped the way the architecture deck groups them.

`users` (migration 004) is the sign-in table. It is not part of this ledger and
is not truncated when the generator replaces billing rows.
Operational tables (the event outbox, dead letters, findings, reports) are not part of
that 23. They are truncated with the ledger so a re-seed does not keep stale failures.
"""

TABLES: tuple[str, ...] = (
    # Customer and product
    "customers",
    "accounts",
    "tariff_plans",
    "subscriptions",
    # Usage and roaming
    "usage_events",
    "roaming_packs",
    # Billing and disputes
    "invoices",
    "invoice_lines",
    "adjustments",
    "disputes",
    # Payments
    "payments",
    "payment_attempts",
    # Entitlements and VAS
    "entitlements",
    "entitlement_balances",
    "vas_subscriptions",
    # Collections / treatment
    "treatment_plans",
    "account_treatment",
    "treatment_exemptions",
    "dunning_events",
    # Operations and governance
    "tickets",
    "fraud_flags",
    "incidents",
    "audit_log",
)

# Insert order respects foreign keys. Truncate uses CASCADE and can list all of them.
INSERT_ORDER: tuple[str, ...] = (
    "customers",
    "tariff_plans",
    "accounts",
    "subscriptions",
    "vas_subscriptions",
    "roaming_packs",
    "entitlements",
    "entitlement_balances",
    "usage_events",
    "invoices",
    "invoice_lines",
    "payments",
    "payment_attempts",
    "tickets",
    "disputes",
    "adjustments",
    "treatment_plans",
    "account_treatment",
    "treatment_exemptions",
    "dunning_events",
    "fraud_flags",
    "incidents",
    "audit_log",
)

# Not part of the 23-table billing model. Truncated on re-seed; not filled by the generator.
OPS_TABLES: tuple[str, ...] = (
    "dead_letter_events",
    "outbox_events",
    "bill_runs",
    "consumer_cursors",
    "ra_findings",
    "report_runs",
)
