-- Phase 3: Langfuse trace id on each copilot turn. Null when tracing is off.

ALTER TABLE agent_runs ADD COLUMN trace_id VARCHAR(64);

CREATE INDEX ix_agent_runs_trace_id ON agent_runs (trace_id);

COMMENT ON COLUMN agent_runs.trace_id IS 'Langfuse trace id for this turn. Null when tracing is off.';
