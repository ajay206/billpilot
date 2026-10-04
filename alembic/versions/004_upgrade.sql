-- Sign-in identities. Not part of the synthetic ledger, so a re-seed does not drop them.
-- Scope is a customer number or a CSR code. Ops has neither. There is no admin role.

CREATE TABLE users (
    id UUID PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(16) NOT NULL,
    customer_number VARCHAR(32),
    csr_code VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_users_username UNIQUE (username),
    CONSTRAINT ck_users_role CHECK (role IN ('customer', 'csr', 'ops')),
    CONSTRAINT ck_users_scope CHECK (
        (role = 'customer' AND customer_number IS NOT NULL AND csr_code IS NULL)
        OR (role = 'csr' AND csr_code IS NOT NULL AND customer_number IS NULL)
        OR (role = 'ops' AND customer_number IS NULL AND csr_code IS NULL)
    )
);

CREATE INDEX ix_users_customer_number ON users (customer_number);
CREATE INDEX ix_users_csr_code ON users (csr_code);

COMMENT ON TABLE users IS 'Demo sign-in. The server reads role and scope from this row. The client cannot choose them.';
