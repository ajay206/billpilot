-- Phase 5: credit profile, and the migration batch that can be rolled back.
-- These tables sit beside the original 23. The billing ledger is unchanged.

CREATE TABLE credit_profiles (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL UNIQUE REFERENCES accounts (id),
    credit_class VARCHAR(16) NOT NULL,
    credit_limit NUMERIC(12, 2) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    set_at TIMESTAMPTZ NOT NULL,
    set_by VARCHAR(64) NOT NULL,
    CONSTRAINT ck_credit_profiles_class CHECK (credit_class IN ('new', 'standard', 'watch')),
    CONSTRAINT ck_credit_profiles_currency CHECK (currency = 'INR'),
    CONSTRAINT ck_credit_profiles_limit CHECK (credit_limit >= 0)
);

CREATE TABLE migration_batches (
    id UUID PRIMARY KEY,
    batch_code VARCHAR(40) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL,
    source_name VARCHAR(200) NOT NULL,
    source_format VARCHAR(8) NOT NULL,
    mapping_version VARCHAR(32) NOT NULL,
    created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    dry_run_at TIMESTAMPTZ,
    signed_off_by VARCHAR(64),
    signed_off_at TIMESTAMPTZ,
    committed_at TIMESTAMPTZ,
    rolled_back_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_migration_batches_status CHECK (
        status IN ('loaded', 'dry_run', 'signed_off', 'committed', 'rolled_back')
    ),
    CONSTRAINT ck_migration_batches_format CHECK (source_format IN ('csv', 'json'))
);

CREATE TABLE migration_records (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES migration_batches (id),
    ordinal INTEGER NOT NULL,
    source_key VARCHAR(96) NOT NULL,
    record_kind VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    reason VARCHAR(64),
    legacy_customer_id VARCHAR(64),
    legacy_plan VARCHAR(64),
    target_plan VARCHAR(32),
    msisdn VARCHAR(20),
    source_balance NUMERIC(12, 2),
    payload JSONB NOT NULL,
    CONSTRAINT uq_migration_records_key UNIQUE (batch_id, source_key),
    CONSTRAINT ck_migration_records_kind CHECK (record_kind IN ('customer', 'service', 'balance')),
    CONSTRAINT ck_migration_records_status CHECK (status IN ('rejected', 'skipped', 'ready', 'migrated'))
);

CREATE INDEX ix_migration_records_batch_id ON migration_records (batch_id, ordinal);

CREATE TABLE migration_links (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES migration_batches (id),
    source_key VARCHAR(96) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,
    entity_id UUID NOT NULL,
    CONSTRAINT uq_migration_links_entity UNIQUE (batch_id, entity_type, entity_id)
);

CREATE INDEX ix_migration_links_batch_id ON migration_links (batch_id);
