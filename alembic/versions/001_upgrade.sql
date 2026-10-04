-- BillPilot Phase 1 schema.
-- Account-centric billing model for a synthetic telecom BSS.
-- Currency is INR only. This is a learning schema, not a vendor product model.

CREATE TABLE customers (
    id UUID PRIMARY KEY,
    customer_number VARCHAR(32) NOT NULL UNIQUE,
    given_name VARCHAR(80) NOT NULL,
    family_name VARCHAR(80) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL,
    city VARCHAR(80) NOT NULL,
    state VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_customers_phone CHECK (left(phone, 3) = '+91')
);

CREATE TABLE accounts (
    id UUID PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customers (id),
    account_number VARCHAR(32) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    billing_cycle_day INTEGER NOT NULL,
    assigned_csr VARCHAR(32) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_accounts_status CHECK (status IN ('active', 'suspended', 'closed')),
    CONSTRAINT ck_accounts_currency CHECK (currency = 'INR'),
    CONSTRAINT ck_accounts_cycle_day CHECK (billing_cycle_day BETWEEN 1 AND 28)
);

CREATE INDEX ix_accounts_customer_id ON accounts (customer_id);
CREATE INDEX ix_accounts_assigned_csr ON accounts (assigned_csr);

CREATE TABLE tariff_plans (
    id UUID PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(80) NOT NULL,
    description TEXT NOT NULL,
    monthly_fee NUMERIC(12, 2) NOT NULL,
    included_voice_minutes INTEGER NOT NULL,
    included_data_mb INTEGER NOT NULL,
    included_sms INTEGER NOT NULL,
    voice_overage_rate NUMERIC(12, 4) NOT NULL,
    data_overage_rate NUMERIC(12, 4) NOT NULL,
    sms_overage_rate NUMERIC(12, 4) NOT NULL,
    roaming_voice_rate NUMERIC(12, 4) NOT NULL,
    roaming_data_rate NUMERIC(12, 4) NOT NULL,
    roaming_sms_rate NUMERIC(12, 4) NOT NULL,
    lifecycle_status VARCHAR(16) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE,
    CONSTRAINT ck_tariff_plans_status CHECK (lifecycle_status IN ('Active', 'Retired')),
    CONSTRAINT ck_tariff_plans_fee CHECK (monthly_fee >= 0)
);

CREATE TABLE subscriptions (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    tariff_plan_id UUID NOT NULL REFERENCES tariff_plans (id),
    msisdn VARCHAR(15) NOT NULL UNIQUE,
    imsi VARCHAR(20) NOT NULL,
    sim_serial VARCHAR(24) NOT NULL,
    status VARCHAR(16) NOT NULL,
    discount_percent NUMERIC(5, 2) NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_subscriptions_status CHECK (status IN ('active', 'suspended', 'cancelled')),
    CONSTRAINT ck_subscriptions_discount CHECK (discount_percent >= 0 AND discount_percent <= 100),
    CONSTRAINT ck_subscriptions_msisdn CHECK (char_length(msisdn) = 10)
);

CREATE INDEX ix_subscriptions_account_id ON subscriptions (account_id);
CREATE INDEX ix_subscriptions_tariff_plan_id ON subscriptions (tariff_plan_id);

CREATE TABLE usage_events (
    id UUID PRIMARY KEY,
    subscription_id UUID NOT NULL REFERENCES subscriptions (id),
    event_type VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    quantity NUMERIC(14, 3) NOT NULL,
    unit VARCHAR(16) NOT NULL,
    rate_applied NUMERIC(12, 4) NOT NULL,
    rated_amount NUMERIC(12, 2) NOT NULL,
    roaming_country VARCHAR(40),
    destination VARCHAR(80),
    billed BOOLEAN NOT NULL DEFAULT FALSE,
    rating_status VARCHAR(16) NOT NULL,
    source_event_id VARCHAR(64) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_usage_events_type CHECK (
        event_type IN ('voice', 'data', 'sms', 'roaming_voice', 'roaming_data', 'roaming_sms')
    ),
    CONSTRAINT ck_usage_events_unit CHECK (unit IN ('minute', 'MB', 'message')),
    CONSTRAINT ck_usage_events_status CHECK (rating_status IN ('rated', 'unbilled', 'duplicate')),
    CONSTRAINT ck_usage_events_quantity CHECK (quantity > 0),
    CONSTRAINT ck_usage_events_amount CHECK (rated_amount >= 0),
    CONSTRAINT ck_usage_events_roaming CHECK (
        (
            event_type IN ('roaming_voice', 'roaming_data', 'roaming_sms')
            AND roaming_country IS NOT NULL
        )
        OR (
            event_type IN ('voice', 'data', 'sms')
            AND roaming_country IS NULL
        )
    )
);

CREATE INDEX ix_usage_events_subscription_started ON usage_events (subscription_id, started_at);
CREATE INDEX ix_usage_events_source ON usage_events (source_event_id);
CREATE INDEX ix_usage_events_unbilled ON usage_events (subscription_id) WHERE billed = FALSE;

CREATE TABLE invoices (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    bill_number VARCHAR(32) NOT NULL UNIQUE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    issue_date DATE NOT NULL,
    due_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL,
    subtotal NUMERIC(12, 2) NOT NULL,
    tax NUMERIC(12, 2) NOT NULL,
    total NUMERIC(12, 2) NOT NULL,
    amount_due NUMERIC(12, 2) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_invoices_status CHECK (status IN ('issued', 'partially_paid', 'paid', 'cancelled')),
    CONSTRAINT ck_invoices_currency CHECK (currency = 'INR'),
    CONSTRAINT ck_invoices_total CHECK (subtotal + tax = total),
    CONSTRAINT ck_invoices_due CHECK (amount_due >= 0 AND amount_due <= total),
    CONSTRAINT ck_invoices_tax CHECK (tax >= 0 AND total >= 0)
);

CREATE INDEX ix_invoices_account_issue ON invoices (account_id, issue_date);

CREATE TABLE invoice_lines (
    id UUID PRIMARY KEY,
    invoice_id UUID NOT NULL REFERENCES invoices (id),
    line_number INTEGER NOT NULL,
    charge_type VARCHAR(20) NOT NULL,
    description TEXT NOT NULL,
    quantity NUMERIC(14, 3) NOT NULL,
    unit_price NUMERIC(12, 4) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    subscription_id UUID REFERENCES subscriptions (id),
    usage_event_id UUID REFERENCES usage_events (id),
    tariff_plan_id UUID REFERENCES tariff_plans (id),
    CONSTRAINT uq_invoice_lines_number UNIQUE (invoice_id, line_number),
    CONSTRAINT ck_invoice_lines_type CHECK (
        charge_type IN (
            'recurring',
            'usage',
            'roaming',
            'vas',
            'addon',
            'discount',
            'adjustment',
            'tax',
            'late_fee'
        )
    ),
    CONSTRAINT ck_invoice_lines_quantity CHECK (quantity > 0)
);

CREATE INDEX ix_invoice_lines_invoice_id ON invoice_lines (invoice_id);
CREATE INDEX ix_invoice_lines_usage_event_id ON invoice_lines (usage_event_id);

CREATE TABLE payments (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    invoice_id UUID REFERENCES invoices (id),
    payment_number VARCHAR(32) NOT NULL UNIQUE,
    amount NUMERIC(12, 2) NOT NULL,
    method VARCHAR(20) NOT NULL,
    status VARCHAR(16) NOT NULL,
    reference VARCHAR(64) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    posted_at TIMESTAMPTZ,
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_payments_method CHECK (method IN ('upi', 'card', 'netbanking', 'cash', 'autopay')),
    CONSTRAINT ck_payments_status CHECK (status IN ('received', 'posted', 'failed', 'reversed')),
    CONSTRAINT ck_payments_currency CHECK (currency = 'INR'),
    CONSTRAINT ck_payments_amount CHECK (amount > 0),
    CONSTRAINT ck_payments_posted CHECK (
        (status = 'posted' AND posted_at IS NOT NULL)
        OR (status <> 'posted')
    )
);

CREATE INDEX ix_payments_account_id ON payments (account_id);
CREATE INDEX ix_payments_invoice_id ON payments (invoice_id);

CREATE TABLE payment_attempts (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    invoice_id UUID REFERENCES invoices (id),
    payment_id UUID REFERENCES payments (id),
    attempt_number INTEGER NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    method VARCHAR(20) NOT NULL,
    status VARCHAR(16) NOT NULL,
    failure_reason VARCHAR(80),
    attempted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_payment_attempts_method CHECK (
        method IN ('upi', 'card', 'netbanking', 'cash', 'autopay')
    ),
    CONSTRAINT ck_payment_attempts_status CHECK (status IN ('succeeded', 'failed', 'pending')),
    CONSTRAINT ck_payment_attempts_amount CHECK (amount > 0),
    CONSTRAINT uq_payment_attempts_number UNIQUE (invoice_id, attempt_number)
);

CREATE INDEX ix_payment_attempts_account_id ON payment_attempts (account_id);

CREATE TABLE tickets (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    ticket_number VARCHAR(32) NOT NULL UNIQUE,
    ticket_type VARCHAR(32) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    summary VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    opened_by VARCHAR(64) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_tickets_severity CHECK (severity IN ('Minor', 'Major', 'Critical')),
    CONSTRAINT ck_tickets_status CHECK (status IN ('open', 'in_progress', 'resolved', 'closed'))
);

CREATE INDEX ix_tickets_account_id ON tickets (account_id);

CREATE TABLE disputes (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    invoice_id UUID REFERENCES invoices (id),
    ticket_id UUID REFERENCES tickets (id),
    status VARCHAR(20) NOT NULL,
    category VARCHAR(32) NOT NULL,
    description TEXT NOT NULL,
    opened_by VARCHAR(64) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    CONSTRAINT ck_disputes_status CHECK (status IN ('open', 'under_review', 'resolved', 'rejected')),
    CONSTRAINT ck_disputes_category CHECK (
        category IN ('billing', 'usage', 'payment', 'treatment', 'entitlement', 'other')
    )
);

CREATE INDEX ix_disputes_account_status ON disputes (account_id, status);

CREATE TABLE adjustments (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    invoice_id UUID REFERENCES invoices (id),
    invoice_line_id UUID REFERENCES invoice_lines (id),
    dispute_id UUID REFERENCES disputes (id),
    adjustment_type VARCHAR(16) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    reason TEXT NOT NULL,
    status VARCHAR(24) NOT NULL,
    proposed_by VARCHAR(64) NOT NULL,
    decided_by VARCHAR(64),
    proposed_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    decision_note TEXT,
    evidence JSONB NOT NULL DEFAULT CAST('{}' AS JSONB),
    CONSTRAINT ck_adjustments_type CHECK (adjustment_type IN ('credit', 'debit')),
    CONSTRAINT ck_adjustments_status CHECK (status IN ('pending_approval', 'applied', 'rejected')),
    CONSTRAINT ck_adjustments_currency CHECK (currency = 'INR'),
    CONSTRAINT ck_adjustments_amount CHECK (amount > 0)
);

CREATE INDEX ix_adjustments_account_id ON adjustments (account_id);
CREATE INDEX ix_adjustments_status ON adjustments (status);

CREATE TABLE vas_subscriptions (
    id UUID PRIMARY KEY,
    subscription_id UUID NOT NULL REFERENCES subscriptions (id),
    product_code VARCHAR(32) NOT NULL,
    name VARCHAR(80) NOT NULL,
    monthly_fee NUMERIC(12, 2) NOT NULL,
    opted_in BOOLEAN NOT NULL,
    status VARCHAR(16) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    CONSTRAINT ck_vas_status CHECK (status IN ('active', 'cancelled')),
    CONSTRAINT ck_vas_fee CHECK (monthly_fee >= 0)
);

CREATE INDEX ix_vas_subscriptions_subscription_id ON vas_subscriptions (subscription_id);

CREATE TABLE roaming_packs (
    id UUID PRIMARY KEY,
    subscription_id UUID NOT NULL REFERENCES subscriptions (id),
    pack_code VARCHAR(32) NOT NULL,
    name VARCHAR(80) NOT NULL,
    zone VARCHAR(40) NOT NULL,
    data_mb INTEGER NOT NULL,
    voice_minutes INTEGER NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL,
    CONSTRAINT ck_roaming_packs_status CHECK (status IN ('scheduled', 'active', 'expired', 'cancelled')),
    CONSTRAINT ck_roaming_packs_window CHECK (valid_to > valid_from),
    CONSTRAINT ck_roaming_packs_price CHECK (price >= 0)
);

CREATE INDEX ix_roaming_packs_subscription_id ON roaming_packs (subscription_id);

CREATE TABLE entitlements (
    id UUID PRIMARY KEY,
    subscription_id UUID NOT NULL REFERENCES subscriptions (id),
    source_type VARCHAR(20) NOT NULL,
    source_ref VARCHAR(80) NOT NULL,
    feature_code VARCHAR(32) NOT NULL,
    allowance_quantity NUMERIC(14, 3) NOT NULL,
    unit VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    resets_on_bill_cycle BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_entitlements_source CHECK (
        source_type IN ('plan', 'addon', 'roaming_pack', 'promo', 'vas')
    ),
    CONSTRAINT ck_entitlements_status CHECK (
        status IN ('active', 'expired', 'pending_activation', 'cancelled')
    ),
    CONSTRAINT ck_entitlements_unit CHECK (unit IN ('minute', 'MB', 'message', 'feature')),
    CONSTRAINT ck_entitlements_allowance CHECK (allowance_quantity >= 0)
);

CREATE INDEX ix_entitlements_subscription_id ON entitlements (subscription_id);

CREATE TABLE entitlement_balances (
    id UUID PRIMARY KEY,
    entitlement_id UUID NOT NULL REFERENCES entitlements (id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    granted_quantity NUMERIC(14, 3) NOT NULL,
    consumed_quantity NUMERIC(14, 3) NOT NULL,
    remaining_quantity NUMERIC(14, 3) NOT NULL,
    reset_at TIMESTAMPTZ,
    CONSTRAINT uq_entitlement_balances_period UNIQUE (entitlement_id, period_start),
    CONSTRAINT ck_entitlement_balances_quantities CHECK (
        granted_quantity >= 0
        AND consumed_quantity >= 0
        AND remaining_quantity >= 0
    )
);

CREATE INDEX ix_entitlement_balances_entitlement_id ON entitlement_balances (entitlement_id);

CREATE TABLE treatment_plans (
    id UUID PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(80) NOT NULL,
    description TEXT NOT NULL,
    reminder_after_days INTEGER NOT NULL,
    soft_bar_after_days INTEGER NOT NULL,
    hard_bar_after_days INTEGER NOT NULL,
    disconnect_after_days INTEGER NOT NULL,
    CONSTRAINT ck_treatment_plans_order CHECK (
        reminder_after_days < soft_bar_after_days
        AND soft_bar_after_days < hard_bar_after_days
        AND hard_bar_after_days < disconnect_after_days
    )
);

CREATE TABLE account_treatment (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    treatment_plan_id UUID NOT NULL REFERENCES treatment_plans (id),
    stage VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    hold_reason VARCHAR(40),
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_account_treatment_stage CHECK (
        stage IN ('none', 'reminder', 'soft_bar', 'hard_bar', 'disconnect')
    ),
    CONSTRAINT ck_account_treatment_status CHECK (status IN ('active', 'held', 'closed'))
);

CREATE UNIQUE INDEX uq_account_treatment_open
    ON account_treatment (account_id)
    WHERE status IN ('active', 'held');

CREATE INDEX ix_account_treatment_account_id ON account_treatment (account_id);

CREATE TABLE treatment_exemptions (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    reason TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    created_by VARCHAR(64) NOT NULL,
    CONSTRAINT ck_treatment_exemptions_window CHECK (valid_to > valid_from)
);

CREATE INDEX ix_treatment_exemptions_account_id ON treatment_exemptions (account_id);

CREATE TABLE dunning_events (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    account_treatment_id UUID NOT NULL REFERENCES account_treatment (id),
    event_type VARCHAR(24) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    notes TEXT,
    promise_pay_by TIMESTAMPTZ,
    promise_amount NUMERIC(12, 2),
    CONSTRAINT ck_dunning_events_type CHECK (
        event_type IN ('reminder', 'soft_bar', 'hard_bar', 'disconnect', 'unbar', 'promise_to_pay')
    )
);

CREATE INDEX ix_dunning_events_account_occurred ON dunning_events (account_id, occurred_at);

CREATE TABLE fraud_flags (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts (id),
    subscription_id UUID REFERENCES subscriptions (id),
    flag_type VARCHAR(32) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    evidence JSONB NOT NULL DEFAULT CAST('{}' AS JSONB),
    CONSTRAINT ck_fraud_flags_severity CHECK (severity IN ('low', 'medium', 'high')),
    CONSTRAINT ck_fraud_flags_status CHECK (status IN ('open', 'cleared'))
);

CREATE INDEX ix_fraud_flags_account_id ON fraud_flags (account_id);

CREATE TABLE incidents (
    id UUID PRIMARY KEY,
    incident_type VARCHAR(40) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    related_entity_type VARCHAR(40),
    related_entity_id UUID,
    CONSTRAINT ck_incidents_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_incidents_status CHECK (status IN ('open', 'acknowledged', 'resolved'))
);

CREATE INDEX ix_incidents_status ON incidents (status);

CREATE TABLE audit_log (
    id UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor_role VARCHAR(16) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(40) NOT NULL,
    resource_id UUID NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    account_id UUID,
    payload JSONB NOT NULL DEFAULT CAST('{}' AS JSONB),
    CONSTRAINT ck_audit_log_role CHECK (actor_role IN ('customer', 'csr', 'ops', 'system'))
);

CREATE INDEX ix_audit_log_request_id ON audit_log (request_id);
CREATE INDEX ix_audit_log_account_id ON audit_log (account_id);
CREATE INDEX ix_audit_log_resource ON audit_log (resource_type, resource_id);
CREATE INDEX ix_audit_log_occurred_at ON audit_log (occurred_at);

COMMENT ON TABLE customers IS 'Synthetic person. One customer may hold several billing accounts.';
COMMENT ON TABLE accounts IS 'Billing account. Currency is INR. assigned_csr is the care scope key.';
COMMENT ON TABLE tariff_plans IS 'Sellable mobile plans and the rates used to price overage.';
COMMENT ON TABLE subscriptions IS 'A mobile product on an account: MSISDN, SIM and chosen plan.';
COMMENT ON TABLE usage_events IS 'Rated voice, data, SMS and roaming records for one subscription.';
COMMENT ON TABLE invoices IS 'A customer bill for one account and one cycle. Header must match its lines.';
COMMENT ON TABLE invoice_lines IS 'One charge, discount, tax or credit on a bill.';
COMMENT ON TABLE payments IS 'Money received against an account. posted means it reduced amount due.';
COMMENT ON TABLE payment_attempts IS 'An autopay or checkout try, which may or may not have a payment row.';
COMMENT ON TABLE adjustments IS 'A credit or debit. Starts pending_approval and is applied only by approval.';
COMMENT ON TABLE disputes IS 'A billing dispute opened by a customer or CSR.';
COMMENT ON TABLE vas_subscriptions IS 'An opted-in or erroneously present value-added service.';
COMMENT ON TABLE roaming_packs IS 'A time-boxed roaming allowance the customer paid for.';
COMMENT ON TABLE entitlements IS 'What a subscription is allowed to use: plan, pack, promo or feature.';
COMMENT ON TABLE entitlement_balances IS 'Granted, consumed and remaining quantity for one entitlement period.';
COMMENT ON TABLE treatment_plans IS 'The reminder, bar and disconnect ladder, measured in days past due.';
COMMENT ON TABLE account_treatment IS 'Where an account currently sits on that ladder.';
COMMENT ON TABLE treatment_exemptions IS 'A window during which an account must not be treated.';
COMMENT ON TABLE dunning_events IS 'Each reminder, bar, promise-to-pay or unbar on an account.';
COMMENT ON TABLE tickets IS 'A trouble ticket. Disputes may point at one.';
COMMENT ON TABLE fraud_flags IS 'A labelled fraud or revenue-assurance pattern, with evidence JSON.';
COMMENT ON TABLE incidents IS 'An operations incident. Phase 1 stores examples; Kafka will raise these later.';
COMMENT ON TABLE audit_log IS 'One row per write: who, what, request id, and the payload.';
