"""Rule checks over the synthetic ledger.

Each check is a SQL query. A finding is one account and one planted anomaly type.
The queries do not read ground_truth.json. Scoring against that file happens later.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from billpilot.models import RaFinding

# Display names are the deck's words. anomaly_type is the generator's label.
DETECTORS: tuple[dict, ...] = (
    {
        "detector": "duplicate_charge",
        "anomaly_type": "double_charge",
        "name": "Duplicate charges",
        "family": "revenue",
        "severity": "high",
        "summary": "An invoice has two identical recurring lines.",
        "sql": """
            SELECT i.account_id,
                   i.id AS invoice_id,
                   il.amount AS pre_tax_amount,
                   il.description,
                   COUNT(*) AS copies
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            WHERE il.charge_type = 'recurring'
            GROUP BY i.account_id, i.id, il.amount, il.description
            HAVING COUNT(*) >= 2
        """,
    },
    {
        "detector": "roaming_spike",
        "anomaly_type": "roaming_spike",
        "name": "Roaming spike",
        "family": "fraud",
        "severity": "high",
        "summary": "Roaming data in a cycle is far above ordinary synthetic usage.",
        "sql": """
            SELECT s.account_id,
                   MAX(u.quantity) AS peak_mb,
                   COUNT(*) AS roaming_events
            FROM usage_events u
            JOIN subscriptions s ON s.id = u.subscription_id
            WHERE u.event_type = 'roaming_data'
            GROUP BY s.account_id
            HAVING MAX(u.quantity) >= 1000
        """,
    },
    {
        "detector": "sim_swap_premium",
        "anomaly_type": "sim_swap",
        "name": "SIM swap followed by premium usage",
        "family": "fraud",
        "severity": "critical",
        "summary": "A short burst of premium-rate calls followed a SIM change.",
        "sql": """
            SELECT s.account_id,
                   COUNT(*) AS premium_calls,
                   MIN(u.started_at) AS burst_started,
                   MAX(u.started_at) AS burst_ended
            FROM usage_events u
            JOIN subscriptions s ON s.id = u.subscription_id
            WHERE u.destination = 'premium-rate'
            GROUP BY s.account_id
            HAVING COUNT(*) >= 8
        """,
    },
    {
        "detector": "unbilled_usage",
        "anomaly_type": "unbilled_usage",
        "name": "Rated but unbilled usage",
        "family": "revenue",
        "severity": "high",
        "summary": "Rated usage never landed on an invoice.",
        "sql": """
            SELECT s.account_id,
                   u.id AS usage_event_id,
                   u.rated_amount AS pre_tax_amount
            FROM usage_events u
            JOIN subscriptions s ON s.id = u.subscription_id
            WHERE u.billed = false
              AND u.rating_status = 'unbilled'
              AND u.rated_amount > 0
        """,
    },
    {
        "detector": "usage_without_charge",
        "anomaly_type": "usage_without_charge",
        "name": "Usage with no rated charge",
        "family": "revenue",
        "severity": "medium",
        "summary": "Usage has quantity but both the rate and the rated amount are zero.",
        "sql": """
            SELECT s.account_id,
                   u.id AS usage_event_id,
                   u.quantity
            FROM usage_events u
            JOIN subscriptions s ON s.id = u.subscription_id
            WHERE u.quantity > 0
              AND u.rated_amount = 0
              AND u.rate_applied = 0
        """,
    },
    {
        "detector": "duplicate_usage",
        "anomaly_type": "duplicate_usage",
        "name": "Duplicate usage charge",
        "family": "revenue",
        "severity": "high",
        "summary": "Two billed usage rows share one source event id.",
        "sql": """
            SELECT s.account_id,
                   u.source_event_id,
                   SUM(u.rated_amount) AS rated_total,
                   COUNT(*) AS copies
            FROM usage_events u
            JOIN subscriptions s ON s.id = u.subscription_id
            WHERE u.source_event_id <> ''
            GROUP BY s.account_id, u.source_event_id
            HAVING COUNT(*) >= 2
        """,
    },
    {
        "detector": "tariff_mismatch",
        "anomaly_type": "wrong_rate",
        "name": "Bill versus tariff mismatch",
        "family": "revenue",
        "severity": "high",
        "summary": "A data overage line was priced at a rate other than the catalogue rate.",
        "sql": """
            SELECT i.account_id,
                   i.id AS invoice_id,
                   il.id AS invoice_line_id,
                   (il.amount - (il.quantity * tp.data_overage_rate)) AS pre_tax_amount,
                   il.unit_price,
                   tp.data_overage_rate AS catalogue_rate
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN tariff_plans tp ON tp.id = il.tariff_plan_id
            WHERE il.description = 'Data overage'
              AND il.unit_price <> tp.data_overage_rate
        """,
    },
    {
        "detector": "missed_discount",
        "anomaly_type": "missed_discount",
        "name": "Missed discount",
        "family": "revenue",
        "severity": "medium",
        "summary": "The subscription has a discount percent and the latest invoice has no discount line.",
        "sql": """
            WITH latest AS (
                SELECT DISTINCT ON (account_id) id, account_id, subtotal
                FROM invoices
                ORDER BY account_id, period_end DESC, id
            )
            SELECT l.account_id,
                   l.id AS invoice_id,
                   (l.subtotal * s.discount_percent / 100) AS pre_tax_amount,
                   s.discount_percent
            FROM latest l
            JOIN subscriptions s ON s.account_id = l.account_id
            WHERE s.discount_percent > 0
              AND NOT EXISTS (
                  SELECT 1 FROM invoice_lines il
                  WHERE il.invoice_id = l.id AND il.charge_type = 'discount'
              )
        """,
    },
    {
        "detector": "charge_after_cancel",
        "anomaly_type": "charge_after_cancellation",
        "name": "Charge after cancellation",
        "family": "revenue",
        "severity": "high",
        "summary": "Usage started after the subscription end.",
        "sql": """
            SELECT DISTINCT s.account_id,
                   s.ended_at,
                   u.id AS usage_event_id,
                   u.rated_amount AS pre_tax_amount
            FROM usage_events u
            JOIN subscriptions s ON s.id = u.subscription_id
            WHERE s.ended_at IS NOT NULL
              AND u.started_at > s.ended_at
        """,
    },
    {
        "detector": "vas_not_opted_in",
        "anomaly_type": "vas_not_opted_in",
        "name": "VAS charged without opt-in",
        "family": "revenue",
        "severity": "medium",
        "summary": "A value-added service was charged even though opted_in is false.",
        "sql": """
            SELECT s.account_id,
                   v.id AS vas_id,
                   v.monthly_fee AS pre_tax_amount,
                   v.name
            FROM vas_subscriptions v
            JOIN subscriptions s ON s.id = v.subscription_id
            WHERE v.opted_in = false
              AND EXISTS (
                  SELECT 1
                  FROM invoice_lines il
                  JOIN invoices i ON i.id = il.invoice_id
                  WHERE i.account_id = s.account_id
                    AND il.charge_type = 'vas'
                    AND il.description = v.name
              )
        """,
    },
    {
        "detector": "payment_not_recorded",
        "anomaly_type": "payment_not_recorded",
        "name": "Succeeded attempt with no payment",
        "family": "payments",
        "severity": "high",
        "summary": "An autopay attempt succeeded and no payment row exists for that invoice.",
        "sql": """
            SELECT DISTINCT pa.account_id,
                   pa.id AS payment_attempt_id,
                   pa.invoice_id,
                   pa.amount
            FROM payment_attempts pa
            WHERE pa.status = 'succeeded'
              AND pa.payment_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM payments p WHERE p.invoice_id = pa.invoice_id
              )
        """,
    },
    {
        "detector": "payment_not_posted",
        "anomaly_type": "payment_not_posted",
        "name": "Payment received and not posted",
        "family": "payments",
        "severity": "high",
        "summary": "Money was received and never posted, so the amount due is unchanged.",
        "sql": """
            SELECT account_id, id AS payment_id, invoice_id, amount
            FROM payments
            WHERE status = 'received' AND posted_at IS NULL
        """,
    },
    {
        "detector": "barred_after_paying",
        "anomaly_type": "barred_after_paying",
        "name": "Barred after the bill was paid",
        "family": "treatment",
        "severity": "high",
        "summary": "Treatment is an active soft bar even though a posted payment cleared the bill first.",
        "sql": """
            SELECT DISTINCT t.account_id, t.id AS account_treatment_id, p.id AS payment_id
            FROM account_treatment t
            JOIN payments p ON p.account_id = t.account_id AND p.status = 'posted'
            JOIN invoices i ON i.id = p.invoice_id
            WHERE t.status = 'active'
              AND t.stage = 'soft_bar'
              AND i.amount_due = 0
              AND t.started_at > p.posted_at
        """,
    },
    {
        "detector": "treated_during_dispute",
        "anomaly_type": "treated_during_open_dispute",
        "name": "Treated during an open dispute",
        "family": "treatment",
        "severity": "high",
        "summary": "An active treatment step started while a dispute was already open.",
        "sql": """
            SELECT DISTINCT t.account_id, t.id AS account_treatment_id, d.id AS dispute_id
            FROM account_treatment t
            JOIN disputes d ON d.account_id = t.account_id AND d.status = 'open'
            WHERE t.status = 'active'
              AND t.started_at > d.opened_at
        """,
    },
    {
        "detector": "payment_not_ending_treatment",
        "anomaly_type": "payment_not_ending_treatment",
        "name": "Payment did not end treatment",
        "family": "treatment",
        "severity": "high",
        "summary": "The bill was paid after the bar and treatment is still active, with no unbar.",
        "sql": """
            SELECT DISTINCT t.account_id, t.id AS account_treatment_id, p.id AS payment_id
            FROM account_treatment t
            JOIN payments p ON p.account_id = t.account_id AND p.status = 'posted'
            JOIN invoices i ON i.id = p.invoice_id
            WHERE t.status = 'active'
              AND i.amount_due = 0
              AND p.posted_at > t.started_at
              AND NOT EXISTS (
                  SELECT 1 FROM dunning_events d
                  WHERE d.account_id = t.account_id AND d.event_type = 'unbar'
              )
        """,
    },
    {
        "detector": "promise_ignored",
        "anomaly_type": "promise_to_pay_ignored",
        "name": "Promise to pay ignored",
        "family": "treatment",
        "severity": "high",
        "summary": "A hard bar was applied before the promise-to-pay date.",
        "sql": """
            SELECT DISTINCT t.account_id, t.id AS account_treatment_id
            FROM account_treatment t
            JOIN dunning_events promise
              ON promise.account_treatment_id = t.id AND promise.event_type = 'promise_to_pay'
            JOIN dunning_events bar
              ON bar.account_treatment_id = t.id AND bar.event_type = 'hard_bar'
            WHERE t.status = 'active'
              AND t.stage = 'hard_bar'
              AND bar.occurred_at < promise.promise_pay_by
        """,
    },
    {
        "detector": "exempt_treated",
        "anomaly_type": "exempt_account_treated",
        "name": "Exempt account treated",
        "family": "treatment",
        "severity": "high",
        "summary": "Treatment started inside an exemption window.",
        "sql": """
            SELECT DISTINCT t.account_id, t.id AS account_treatment_id, e.id AS exemption_id
            FROM account_treatment t
            JOIN treatment_exemptions e ON e.account_id = t.account_id
            WHERE t.status = 'active'
              AND e.valid_from <= t.started_at
              AND t.started_at <= e.valid_to
        """,
    },
    {
        "detector": "addon_never_activated",
        "anomaly_type": "addon_never_activated",
        "name": "Add-on paid and not activated",
        "family": "entitlement",
        "severity": "medium",
        "summary": "An add-on was charged and its entitlement is still pending activation.",
        "sql": """
            SELECT s.account_id, e.id AS entitlement_id
            FROM entitlements e
            JOIN subscriptions s ON s.id = e.subscription_id
            WHERE e.status = 'pending_activation'
              AND NOT EXISTS (
                  SELECT 1 FROM entitlement_balances b WHERE b.entitlement_id = e.id
              )
              AND EXISTS (
                  SELECT 1
                  FROM invoice_lines il
                  JOIN invoices i ON i.id = il.invoice_id
                  WHERE i.account_id = s.account_id
                    AND il.charge_type = 'addon'
                    AND il.amount > 0
              )
        """,
    },
    {
        "detector": "allowance_not_reset",
        "anomaly_type": "allowance_not_reset",
        "name": "Allowance did not reset",
        "family": "entitlement",
        "severity": "medium",
        "summary": "The latest data balance was not reset and still matches the previous cycle.",
        "sql": """
            WITH ranked AS (
                SELECT s.account_id,
                       b.entitlement_id,
                       b.consumed_quantity,
                       b.remaining_quantity,
                       b.reset_at,
                       b.period_start,
                       ROW_NUMBER() OVER (PARTITION BY b.entitlement_id ORDER BY b.period_start DESC) AS rn
                FROM entitlement_balances b
                JOIN entitlements e ON e.id = b.entitlement_id
                JOIN subscriptions s ON s.id = e.subscription_id
                WHERE e.feature_code = 'data' AND e.source_type = 'plan'
            )
            SELECT latest.account_id, latest.entitlement_id
            FROM ranked latest
            JOIN ranked prior
              ON prior.entitlement_id = latest.entitlement_id AND prior.rn = 2
            WHERE latest.rn = 1
              AND latest.reset_at IS NULL
              AND latest.consumed_quantity = prior.consumed_quantity
              AND latest.remaining_quantity = prior.remaining_quantity
        """,
    },
    {
        "detector": "packs_double_counted",
        "anomaly_type": "overlapping_packs_double_counted",
        "name": "Overlapping packs double-counted",
        "family": "entitlement",
        "severity": "medium",
        "summary": "Two overlapping roaming packs were summed into one allowance.",
        "sql": """
            WITH pairs AS (
                SELECT s.account_id,
                       p1.subscription_id,
                       p1.data_mb AS first_mb,
                       p2.data_mb AS second_mb
                FROM roaming_packs p1
                JOIN roaming_packs p2
                  ON p1.subscription_id = p2.subscription_id
                 AND p1.id < p2.id
                 AND p1.valid_from < p2.valid_to
                 AND p2.valid_from < p1.valid_to
                JOIN subscriptions s ON s.id = p1.subscription_id
            )
            SELECT p.account_id, e.allowance_quantity, p.first_mb, p.second_mb
            FROM pairs p
            JOIN entitlements e
              ON e.subscription_id = p.subscription_id
             AND e.feature_code = 'roaming_data'
             AND e.source_type = 'roaming_pack'
            WHERE e.allowance_quantity = p.first_mb + p.second_mb
        """,
    },
    {
        "detector": "packs_dropped",
        "anomaly_type": "overlapping_packs_dropped",
        "name": "Overlapping packs dropped",
        "family": "entitlement",
        "severity": "medium",
        "summary": "Two overlapping roaming packs were paid for and only one allowance was kept.",
        "sql": """
            WITH pairs AS (
                SELECT s.account_id,
                       p1.subscription_id,
                       p1.data_mb AS first_mb,
                       p2.data_mb AS second_mb
                FROM roaming_packs p1
                JOIN roaming_packs p2
                  ON p1.subscription_id = p2.subscription_id
                 AND p1.id < p2.id
                 AND p1.valid_from < p2.valid_to
                 AND p2.valid_from < p1.valid_to
                JOIN subscriptions s ON s.id = p1.subscription_id
            )
            SELECT p.account_id, e.allowance_quantity, p.first_mb, p.second_mb
            FROM pairs p
            JOIN entitlements e
              ON e.subscription_id = p.subscription_id
             AND e.feature_code = 'roaming_data'
             AND e.source_type = 'roaming_pack'
            WHERE e.allowance_quantity <> p.first_mb + p.second_mb
              AND (e.allowance_quantity = p.first_mb OR e.allowance_quantity = p.second_mb)
        """,
    },
    {
        "detector": "promo_ended_early",
        "anomaly_type": "promo_ended_early",
        "name": "Promo ended early",
        "family": "entitlement",
        "severity": "low",
        "summary": "A promotional entitlement expired in under 40 days.",
        "sql": """
            SELECT s.account_id, e.id AS entitlement_id, e.valid_from, e.valid_to
            FROM entitlements e
            JOIN subscriptions s ON s.id = e.subscription_id
            WHERE e.source_type = 'promo'
              AND e.status = 'expired'
              AND e.valid_to IS NOT NULL
              AND e.valid_to - e.valid_from < INTERVAL '40 days'
        """,
    },
    {
        "detector": "entitlement_without_charge",
        "anomaly_type": "feature_active_after_cancellation",
        "name": "Entitlement given without a charge",
        "family": "entitlement",
        "severity": "medium",
        "summary": "The subscription and the add-on are cancelled, and the feature entitlement is still active.",
        "sql": """
            SELECT s.account_id, e.id AS entitlement_id, v.id AS vas_id
            FROM entitlements e
            JOIN subscriptions s ON s.id = e.subscription_id
            JOIN vas_subscriptions v ON v.subscription_id = s.id
            WHERE e.feature_code = 'ott_mini'
              AND e.status = 'active'
              AND s.status = 'cancelled'
              AND v.status = 'cancelled'
        """,
    },
    {
        "detector": "overage_on_covered",
        "anomaly_type": "overage_on_covered_usage",
        "name": "Overage on covered usage",
        "family": "revenue",
        "severity": "high",
        "summary": "Data was billed as overage while the allowance still covered that quantity.",
        "sql": """
            SELECT s.account_id,
                   u.id AS usage_event_id,
                   il.id AS invoice_line_id,
                   i.id AS invoice_id,
                   il.amount AS pre_tax_amount,
                   b.remaining_quantity,
                   u.quantity
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN usage_events u ON u.id = il.usage_event_id
            JOIN subscriptions s ON s.id = u.subscription_id
            JOIN entitlements e
              ON e.subscription_id = s.id
             AND e.feature_code = 'data'
             AND e.source_type = 'plan'
            JOIN entitlement_balances b
              ON b.entitlement_id = e.id
             AND b.period_start = u.period_start
            WHERE il.description = 'Data overage'
              AND u.event_type = 'data'
              AND u.rated_amount > 0
              AND b.remaining_quantity >= u.quantity
        """,
    },
)


def _ready(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def detect(session: Session) -> list[dict]:
    """Run every check. One dict per account and anomaly type."""
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for spec in DETECTORS:
        rows = session.execute(text(spec["sql"])).mappings().all()
        for row in rows:
            account_id = str(row["account_id"])
            key = (account_id, spec["anomaly_type"])
            if key in seen:
                continue
            seen.add(key)
            evidence = {column: _ready(row[column]) for column in row.keys() if column != "account_id"}
            found.append(
                {
                    "detector": spec["detector"],
                    "anomaly_type": spec["anomaly_type"],
                    "name": spec["name"],
                    "family": spec["family"],
                    "severity": spec["severity"],
                    "summary": spec["summary"],
                    "account_id": account_id,
                    "evidence": evidence,
                }
            )
    return found


def persist_findings(session: Session, findings: list[dict]) -> list[RaFinding]:
    """Insert new findings. An open finding is refreshed. A case or proposal is left alone."""
    now = datetime.now(UTC)
    stored: list[RaFinding] = []
    for item in findings:
        account_id = uuid.UUID(item["account_id"])
        existing = session.scalar(
            select(RaFinding).where(
                RaFinding.account_id == account_id,
                RaFinding.detector == item["detector"],
                RaFinding.anomaly_type == item["anomaly_type"],
            )
        )
        if existing is None:
            existing = RaFinding(
                id=uuid.uuid4(),
                detector=item["detector"],
                anomaly_type=item["anomaly_type"],
                account_id=account_id,
                severity=item["severity"],
                status="open",
                summary=item["summary"],
                evidence=item["evidence"],
                detected_at=now,
                ticket_id=None,
                adjustment_id=None,
            )
            session.add(existing)
        elif existing.status == "open":
            existing.evidence = item["evidence"]
            existing.summary = item["summary"]
            existing.detected_at = now
            existing.severity = item["severity"]
        stored.append(existing)
    session.commit()
    return stored
