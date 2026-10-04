-- Operational event store, failure records, detector findings, and report snapshots.
-- The 23 billing tables stay the ledger. These tables are the operations layer.

ALTER TABLE incidents ADD COLUMN account_id UUID REFERENCES accounts (id);
ALTER TABLE incidents ADD COLUMN source_event_id UUID;
ALTER TABLE incidents ADD COLUMN evidence JSONB NOT NULL DEFAULT CAST('{}' AS JSONB);

CREATE UNIQUE INDEX uq_incidents_source_event ON incidents (source_event_id);

CREATE INDEX ix_incidents_account_id ON incidents (account_id);
CREATE INDEX ix_incidents_type_status ON incidents (incident_type, status);

CREATE TABLE outbox_events (
    id UUID PRIMARY KEY,
    topic VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    account_id UUID REFERENCES accounts (id) ON DELETE CASCADE,
    occurred_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    idempotency_key VARCHAR(160),
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    CONSTRAINT ck_outbox_status CHECK (status IN ('pending', 'queued', 'processing', 'published', 'dead')),
    CONSTRAINT ck_outbox_retry CHECK (retry_count >= 0),
    CONSTRAINT uq_outbox_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX ix_outbox_status_occurred ON outbox_events (status, occurred_at);
CREATE INDEX ix_outbox_topic_status ON outbox_events (topic, status);

CREATE TABLE dead_letter_events (
    id UUID PRIMARY KEY,
    outbox_event_id UUID NOT NULL REFERENCES outbox_events (id) ON DELETE CASCADE,
    topic VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    error TEXT NOT NULL,
    retry_count INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,
    replay_event_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    replayed_at TIMESTAMPTZ,
    CONSTRAINT ck_dlq_status CHECK (status IN ('open', 'replayed')),
    CONSTRAINT uq_dlq_outbox UNIQUE (outbox_event_id),
    CONSTRAINT uq_dlq_replay UNIQUE (replay_event_id)
);

CREATE INDEX ix_dlq_status ON dead_letter_events (status, created_at);

CREATE TABLE bill_runs (
    id UUID PRIMARY KEY,
    run_key VARCHAR(80) NOT NULL,
    account_id UUID REFERENCES accounts (id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    error TEXT,
    source_event_id UUID,
    CONSTRAINT ck_bill_run_status CHECK (status IN ('started', 'finished', 'failed', 'stuck')),
    CONSTRAINT uq_bill_runs_key UNIQUE (run_key)
);

CREATE INDEX ix_bill_runs_status ON bill_runs (status, started_at);

CREATE TABLE consumer_cursors (
    consumer_name VARCHAR(64) NOT NULL,
    topic VARCHAR(64) NOT NULL,
    committed_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (consumer_name, topic)
);

CREATE TABLE ra_findings (
    id UUID PRIMARY KEY,
    detector VARCHAR(64) NOT NULL,
    anomaly_type VARCHAR(64) NOT NULL,
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL,
    summary TEXT NOT NULL,
    evidence JSONB NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    ticket_id UUID REFERENCES tickets (id),
    adjustment_id UUID REFERENCES adjustments (id),
    CONSTRAINT ck_ra_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_ra_status CHECK (status IN ('open', 'case_opened', 'adjustment_proposed', 'dismissed')),
    CONSTRAINT uq_ra_account_detector UNIQUE (account_id, detector, anomaly_type)
);

CREATE INDEX ix_ra_findings_status ON ra_findings (status, detected_at);

CREATE TABLE report_runs (
    id UUID PRIMARY KEY,
    report_key VARCHAR(40) NOT NULL,
    grain VARCHAR(16) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    generated_by VARCHAR(64) NOT NULL,
    row_count INTEGER NOT NULL,
    payload JSONB NOT NULL,
    CONSTRAINT ck_report_grain CHECK (grain IN ('daily', 'monthly')),
    CONSTRAINT ck_report_period CHECK (period_end > period_start),
    CONSTRAINT uq_report_period UNIQUE (report_key, grain, period_start, period_end)
);

CREATE INDEX ix_report_runs_generated ON report_runs (generated_at DESC);

COMMENT ON TABLE outbox_events IS 'Billing events. Postgres mode consumers read pending rows. Redpanda mode relays them onto the broker.';
COMMENT ON TABLE dead_letter_events IS 'Events the failure consumer could not apply. Replay is an ops action and is idempotent.';
COMMENT ON TABLE bill_runs IS 'Bill-run lifecycle built from bill.run events. A started run that never finishes becomes stuck.';
COMMENT ON TABLE consumer_cursors IS 'How far the failure consumer has committed, per topic.';
COMMENT ON TABLE ra_findings IS 'Rule-detector output over the synthetic ledger, with the evidence row.';
COMMENT ON TABLE report_runs IS 'A daily or monthly report snapshot. Every figure is a SQL aggregate.';
