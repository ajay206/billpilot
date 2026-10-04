DROP TABLE IF EXISTS report_runs;
DROP TABLE IF EXISTS ra_findings;
DROP TABLE IF EXISTS consumer_cursors;
DROP TABLE IF EXISTS bill_runs;
DROP TABLE IF EXISTS dead_letter_events;
DROP TABLE IF EXISTS outbox_events;

DROP INDEX IF EXISTS uq_incidents_source_event;
DROP INDEX IF EXISTS ix_incidents_account_id;
DROP INDEX IF EXISTS ix_incidents_type_status;

ALTER TABLE incidents DROP COLUMN IF EXISTS evidence;
ALTER TABLE incidents DROP COLUMN IF EXISTS source_event_id;
ALTER TABLE incidents DROP COLUMN IF EXISTS account_id;
