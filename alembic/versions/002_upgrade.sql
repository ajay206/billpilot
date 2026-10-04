-- Phase 2: policy chunks (pgvector) and one row per copilot turn.
-- The 23 billing tables are unchanged. agent_runs points at audit_log.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
    id UUID PRIMARY KEY,
    doc_id VARCHAR(80) NOT NULL,
    title VARCHAR(200) NOT NULL,
    section VARCHAR(200) NOT NULL,
    source_path VARCHAR(300) NOT NULL,
    body TEXT NOT NULL,
    embedding vector(256) NOT NULL,
    CONSTRAINT uq_knowledge_chunks_doc_section UNIQUE (doc_id, section)
);

CREATE INDEX ix_knowledge_chunks_doc_id ON knowledge_chunks (doc_id);

CREATE TABLE agent_runs (
    id UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    persona VARCHAR(16) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    account_id UUID,
    user_message TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    refusal BOOLEAN NOT NULL,
    grounded BOOLEAN NOT NULL,
    tool_calls JSONB NOT NULL,
    citations JSONB NOT NULL,
    proposed_actions JSONB NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    estimated_cost_usd NUMERIC(14, 6) NOT NULL,
    latency_ms INTEGER NOT NULL,
    model VARCHAR(80) NOT NULL,
    audit_log_id UUID NOT NULL REFERENCES audit_log (id),
    CONSTRAINT ck_agent_runs_persona CHECK (persona IN ('customer', 'csr', 'ops')),
    CONSTRAINT ck_agent_runs_tokens CHECK (prompt_tokens >= 0 AND completion_tokens >= 0),
    CONSTRAINT ck_agent_runs_cost CHECK (estimated_cost_usd >= 0),
    CONSTRAINT ck_agent_runs_latency CHECK (latency_ms >= 0)
);

CREATE INDEX ix_agent_runs_request_id ON agent_runs (request_id);
CREATE INDEX ix_agent_runs_occurred_at ON agent_runs (occurred_at);
CREATE INDEX ix_agent_runs_audit_log_id ON agent_runs (audit_log_id);

COMMENT ON TABLE knowledge_chunks IS 'Synthetic policy and runbook sections, with a 256-dimension embedding.';
COMMENT ON TABLE agent_runs IS 'One copilot turn: prompt, tool calls, citations, proposals, tokens and estimated cost.';
