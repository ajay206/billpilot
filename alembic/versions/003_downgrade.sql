DROP INDEX IF EXISTS ix_agent_runs_trace_id;
ALTER TABLE agent_runs DROP COLUMN IF EXISTS trace_id;
