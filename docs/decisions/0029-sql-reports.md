# Reports are SQL snapshots

## Decision

Daily and monthly reports for billing, collections and treatment, disputes and credits, payments, and agent usage and cost are `SELECT` aggregates. The window is the latest invoice `issue_date` and that calendar month. Nothing in the payload is a constant typed into the report. `billpilot reports generate`, `POST /ops/reports/generate`, and an in-process loop all call the same builders. A repeat for the same key, grain, and period updates the existing `report_runs` row.

Render has no worker process. The loop starts inside the web process when `REPORT_SCHEDULE_SECONDS` is greater than zero (21600 on Render and in Compose). Tests set it to 0. CSV is `GET /ops/reports/{id}/csv`. The ops page also builds a CSV in the browser from the JSON so the shared API client does not grow a text download method.

## Alternatives

- A cron container. The free Render service is one web process.
- Hardcoded demo totals. A seed change would leave the page lying.
- A warehouse export. The ledger is already small enough to aggregate in Postgres.

## Why

The page has to stay true when the generator changes. Scheduling inside the process is the only scheduler the free tier has.
