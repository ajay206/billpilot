# BillPilot

BillPilot is an AI copilot for telecom billing and operations. Phase 1 is the mock billing system: a PostgreSQL ledger of synthetic customers, and a FastAPI service whose resources are shaped like TM Forum Open APIs. Phase 2 is the copilot: a tool-calling agent, a small policy corpus, an audit row per turn, a CLI, `POST /agent/chat`, and an evaluation harness. Phase 3 is the product surface: a customer portal, a CSR console, and an ops control tower, served by the same process, plus optional Langfuse traces and a free-tier deploy. Sign-in replaced the persona switcher. The browser session carries a user id. Role and scope are read from the `users` table on the server. Phase 4 is the operations layer: a billing-event pipeline, a failure dashboard, SQL reports, rule-based fraud and revenue checks, and a CSR troubleshooting assistant.

Money and service changes stay on the Phase 1 approval queue. The copilot proposes a credit. It cannot apply one. Onboarding and launch are later phases. See [Roadmap](#roadmap).

## Synthetic data only

Every customer, bill, payment, and fault in this repository is generated. Nothing here is a real subscriber, a real invoice, or a vendor's product. Do not add operator data, vendor source, or internal product names. The generator uses public telecom ideas (plans, usage, GST, collections) and the `en_IN` Faker locale.

This API is a **learning mock**. It is not a certified or conformant TM Forum implementation. The paths and resource names follow the Open APIs closely enough that a later assistant can call them as tools. The payloads are a readable subset, not the full specification.

## Architecture

```mermaid
flowchart LR
  subgraph phase2 [Phase 2]
    CLI[billpilot ask]
    Chat[POST /agent/chat]
    Loop[Agent loop]
    Guard[Guardrails]
    Tools[Persona tools]
    RAG[Policy search]
  end
  subgraph phase1 [Phase 1]
    API[FastAPI mock BSS]
    DB[(PostgreSQL and pgvector)]
    Gen[Synthetic generator]
  end
  subgraph phase3 [Phase 3]
    UI[Signed-in UI]
    Trace[Langfuse spans]
  end
  subgraph phase4 [Phase 4]
    Broker[Outbox and Redpanda]
    Failures[Failure dashboard]
    Reports[SQL reports]
    Checks[Fraud and revenue checks]
  end
  subgraph later [Later phases]
    Onboard[Phase 5 onboarding]
    Launch[Phase 6 launch]
  end
  CLI --> Loop
  Chat --> Loop
  Loop --> Guard
  Loop --> Tools
  Loop --> RAG
  Tools -->|X-API-Key| API
  RAG --> DB
  API --> DB
  Gen --> DB
  Loop --> DB
  UI -->|session cookie| API
  Loop --> Trace
  API --> Broker
  Broker --> Failures
  DB --> Reports
  DB --> Checks
```

The database is the system of record. The API translates internal words (`issued`, `posted`, `soft_bar`) into TMF-like words (`sent`, `done`, a trouble-ticket status). Writes that move money start as `pending_approval`. A different role applies them. Every write, including a copilot turn, is appended to `audit_log`.

The copilot does not query the billing tables. Its tools call the HTTP API with the caller's key. Policy text is the exception: `docs/knowledge/` is embedded into `knowledge_chunks` and searched in process. A turn is stored on `agent_runs` and linked to the audit row. Design notes for each of those choices are in [docs/decisions](docs/decisions).

## Quickstart

Requirements: Docker, and for tests a local Python 3.12.

```bash
docker compose up --build
```

That starts Postgres and a single-node Redpanda, runs migrations, seeds 500 customers across 6 months, seeds the demo users, and serves the API and the UI from one process. Open <http://localhost:8000>. The login page lists the demo accounts. After sign-in, a customer lands on <http://localhost:8000/customer>, a CSR on <http://localhost:8000/csr>, and ops on <http://localhost:8000/ops>. The API reference is <http://localhost:8000/docs>.

With no model key, a banner says the copilot is in demo mode. A laptop with limited RAM should use the smaller seed in [How to test locally](docs/deploy.md#how-to-test-locally).

![Sign in](docs/screenshots/login.png)

![Customer portal](docs/screenshots/customer.png)

![CSR console](docs/screenshots/csr.png)

![Ops control tower](docs/screenshots/ops.png)

![Failure dashboard](docs/screenshots/failures.png)

![Reports](docs/screenshots/reports.png)

![Fraud and revenue findings](docs/screenshots/findings.png)

![CSR troubleshooting](docs/screenshots/troubleshoot.png)

Demo users (synthetic portfolio only — do not reuse these passwords anywhere else):

| User | Password | Role | Sees |
| --- | --- | --- | --- |
| `priya.sharma` | `demo-priya` | Customer | `CUST-000001` only |
| `arjun.mehta` | `demo-arjun` | Customer | `CUST-000003` only |
| `neha.iyer` | `demo-neha` | Customer | `CUST-000005` only |
| `ananya.rao` | `demo-ananya` | CSR | Accounts assigned to `CSR-A` |
| `vikram.nair` | `demo-vikram` | CSR | Accounts assigned to `CSR-B` |
| `meera.kapoor` | `demo-meera` | Ops | Every account, approvals, runs, and audit |

The same scopes are available to curl and `billpilot ask` through API keys. Those keys are not in the frontend bundle.

| Persona | Header | Sees |
| --- | --- | --- |
| Customer `CUST-000001` | `X-API-Key: dev-customer-key` | That customer's accounts |
| CSR `CSR-A` | `X-API-Key: dev-csr-key` | Accounts assigned to CSR-A |
| Ops | `X-API-Key: dev-ops-key` | Every account, and approvals |

```bash
curl -s -H 'X-API-Key: dev-customer-key' \
  'http://localhost:8000/tmf-api/customerBillManagement/v4/customerBill?limit=2'
```

Copy `.env.example` to `.env` to change the seed, the customer count, or the keys. Compose reads those variables. The database host inside Compose is `postgres`; do not point `DATABASE_URL` at `localhost` for the containers.

Seed again after changing the counts:

```bash
docker compose run --rm seed
```

`docker compose up` does not re-seed once the seed container has already exited successfully. The API container only migrates on startup, so a restart does not wipe the ledger.

Ground truth for the planted faults is written to `data/ground_truth.json` (gitignored).

### Pull a published image

GitHub Actions publishes `ghcr.io/ajay206/billpilot` on pushes to `main` (tags `latest` and the short commit SHA) and on version tags `v*`. Pull requests only build the image; they do not push it.

After the first publish, set the package visibility to **Public** once, under the package settings on GitHub. Until that is done, a pull from outside this repository is rejected.

```bash
docker pull ghcr.io/ajay206/billpilot:latest
```

The image migrates on startup. If the ledger is empty it seeds before listening, and it serves the persona UI from the same port as the API. Compose below still runs an explicit seed so a laptop load of 500 customers finishes before the API starts. The API then sees the rows and skips a second seed:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: billpilot
      POSTGRES_PASSWORD: billpilot
      POSTGRES_DB: billpilot
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U billpilot -d billpilot"]
      interval: 5s
      timeout: 5s
      retries: 20

  seed:
    image: ghcr.io/ajay206/billpilot:latest
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+psycopg://billpilot:billpilot@postgres:5432/billpilot
    volumes:
      - ./data:/app/data
    command: ["billpilot", "migrate-and-seed"]

  api:
    image: ghcr.io/ajay206/billpilot:latest
    depends_on:
      seed:
        condition: service_completed_successfully
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+psycopg://billpilot:billpilot@postgres:5432/billpilot
      API_KEY_CUSTOMER: dev-customer-key
      API_KEY_CSR: dev-csr-key
      API_KEY_OPS: dev-ops-key
      CUSTOMER_NUMBER: CUST-000001
      CSR_CODE: CSR-A
      SESSION_SECRET: dev-session-secret
    ports:
      - "8000:8000"
```

### Tests

```bash
pip install -e ".[dev]"
make test
```

`make test` starts Postgres, creates a database named `billpilot_test`, then runs ruff and pytest. Tests refuse any other database name.

The persona UI has its own tests:

```bash
cd web && npm ci && npm test
```

CI runs both. A free-tier deploy (Neon Postgres, Render web service, optional Langfuse Hobby) is written up in [docs/deploy.md](docs/deploy.md). `render.yaml` is the blueprint. The container migrates and seeds an empty database before it listens.

## API

All TMF-shaped routes are under `/tmf-api`. Lists accept `offset` and `limit` (default 20, max 100) and return `X-Total-Count` and `X-Result-Count`.

| Method | Path | Who can call it |
| --- | --- | --- |
| GET | `/customerBillManagement/v4/customerBill` | customer, csr, ops, within scope |
| GET | `/customerBillManagement/v4/appliedCustomerBillingRate` | same |
| GET, POST | `/customerBillManagement/v4/customerBillDispute` | read: all three; create: customer, csr |
| GET, POST | `/customerBillManagement/v4/billAdjustment` | read: all three; propose: csr only |
| POST | `/customerBillManagement/v4/billAdjustment/{id}/approve` | ops, and not the proposer |
| GET | `/usageManagement/v4/usage` | all three, within scope |
| GET | `/productCatalogManagement/v4/productOffering` | any authenticated role |
| GET | `/paymentManagement/v4/payment` | all three, within scope |
| GET | `/paymentManagement/v4/paymentAttempt` | same; a small extension so an unposted payment stays visible |
| GET | `/productInventory/v4/product` | subscription, VAS, and entitlement |
| GET, POST | `/troubleTicket/v4/troubleTicket` | read: all three; create: csr only |
| GET | `/prepayBalanceManagement/v4/bucket` and `/balance` | TMF654 buckets; `/balance` is the deck's name for the same read |
| GET | `/accountManagement/v4/billingAccount` | all three, within scope; treatment stage, status, hold, exemption |
| GET | `/accountManagement/v4/fraudFlag` | all three, within scope; synthetic roaming-spike and SIM-swap flags, read only |
| GET | `/ops/auditLog` | ops |
| POST | `/auth/login` | public. Sets the session cookie. |
| POST | `/auth/logout` | the signed-in user |
| GET | `/auth/me` | the signed-in user. Role and scope come from `users`. |
| GET | `/auth/demo-accounts` | public. The synthetic demo passwords, marked demo-only. |
| POST | `/agent/chat` | the session or the API key chooses the persona; body is `message` and optional `accountId` |
| GET | `/health` | public. Includes `demoMode` and `tracing` |
| GET | `/ops/agentRuns` | ops. Cost, latency, tokens, decision tier, trace id |
| GET | `/knowledge/section` | any persona. One cited policy section, for the UI |

Filters use dotted names where the Open API does: `billingAccount.id`, `billNo`, `billDate.gte`, `usageType`, `product.id`.

A proposed adjustment does not change the bill. `decision=approve` applies it in one transaction. `decision=reject` leaves the bill alone. Approving twice returns 409.

Asking for an account outside your scope returns 403, including when the id exists. A missing id returns 404. That is a deliberate, documented trade-off: the mock prefers a clear "not your account" over hiding existence.

## What the generator plants

Default seed `42`, 500 customers, 6 months, **92 labelled anomalies** across 23 types. Counts are `ANOMALY_COUNTS` as JSON, or `GeneratorConfig` in code. Tests use one of each type and 48 customers.

| Type | Default count |
| --- | --- |
| double_charge | 6 |
| roaming_spike | 4 |
| wrong_rate | 6 |
| missed_discount | 6 |
| charge_after_cancellation | 4 |
| vas_not_opted_in | 4 |
| payment_not_recorded | 4 |
| payment_not_posted | 4 |
| unbilled_usage | 6 |
| duplicate_usage | 6 |
| sim_swap | 3 |
| barred_after_paying | 3 |
| treated_during_open_dispute | 3 |
| payment_not_ending_treatment | 3 |
| promise_to_pay_ignored | 3 |
| exempt_account_treated | 3 |
| addon_never_activated | 4 |
| allowance_not_reset | 4 |
| overlapping_packs_double_counted | 3 |
| overlapping_packs_dropped | 3 |
| promo_ended_early | 3 |
| feature_active_after_cancellation | 3 |
| overage_on_covered_usage | 4 |

Five healthy controls are also labelled in the same file: an unpaid account on the correct ladder, an exemption that is respected, a dispute that holds treatment, a promise that is honoured, and a failed autopay that is later posted. They are not faults.

Apart from those faults, invoices balance: line amounts sum to the total, tax is 18% of the pre-tax subtotal, and amount due is the total minus posted payments. Currency is INR.

### Billing simplifications worth saying out loud

- One GST line at 18%. Not split into CGST and SGST.
- The generator builds one account and one subscription per customer. The schema allows more.
- Applying a credit does not recompute GST. The tax line stays; the adjustment line is signed so the lines still sum to the new total.
- Crediting an already-paid bill reduces the total and can leave amount due at zero. It does not create a cash refund.
- The collections ladder is reminder at 3 days past due, soft bar at 10, hard bar at 20, disconnect at 45.
- An unpaid bill whose due date is already past gets a flat ₹50 late fee, plus GST. A failed autopay that is later posted is a labelled healthy control, not a fault.
- The clock inside the generator is 1 October 2026. It does not read the wall clock. Live API writes do.
- Rate limits are counted in this process only. They are not shared across replicas.

## Copilot

The default model backend is `fake`: a scripted playbook, no network, no key, and a price of zero. That is what `docker compose up` and CI use. A hosted model is opt-in. Copy `.env.example` and set:

```bash
LLM_BACKEND=api
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

Any host that accepts `POST {LLM_BASE_URL}/chat/completions` works. Do not add a local model runtime. Embeddings default to `EMBEDDING_BACKEND=hash` (no download). `EMBEDDING_BACKEND=api` calls `{LLM_BASE_URL}/embeddings` and must return 256 dimensions. Reindex after changing it: `billpilot knowledge reindex`.

Langfuse traces a turn only when `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are all set. The SDK is installed with the app. One trace per chat (`billpilot.chat`) or troubleshooting turn (`billpilot.troubleshoot`) contains the guardrail check, each model call with tokens and estimated cost, each tool call, retrieval with the cited doc ids, the output check, and the decision. A troubleshooting turn also has a `troubleshoot.start` span. The trace id is stored on `agent_runs` and shown in the ops dashboard. If a variable is missing, or Langfuse is down, the turn still answers. CI and `docker compose up` leave the keys empty. The free Hobby setup is in [docs/deploy.md](docs/deploy.md).

### Ask

Start the stack, then:

```bash
billpilot ask --persona customer "Explain my latest bill, line by line, against last month and the tariff."
```

CSR and ops need an account id. Planted faults alternate assignees: even indexes are `CSR-A`, odd indexes are `CSR-B` (`assigned_csr` is `CSR-A` when `index % 2 == 0`). The first anomaly is index 1, so a double charge is `CSR-B`. The default `CSR_CODE` is `CSR-A` and will not see that account. For a manual CSR session on an odd-index fault, set `CSR_CODE=CSR-B` and use the CSR key. The eval harness rebinds the CSR code per case, so you do not set this for `python -m billpilot.evals`.

The same turn is `POST /agent/chat` with the persona's `X-API-Key`, or with the browser session. The body cannot pick a different persona. A session cookie has to send `X-CSRF-Token` on that POST.

A credit proposal stays `pending_approval`. Ops approves it with the existing endpoint:

```bash
curl -s -X POST -H 'X-API-Key: dev-ops-key' -H 'Content-Type: application/json' \
  -d '{"decision":"approve"}' \
  http://localhost:8000/tmf-api/customerBillManagement/v4/billAdjustment/<id>/approve
```

### Evals

The harness builds 72 labelled cases from `data/ground_truth.json` (or from the generator if that file is missing). Counts: guardrail 15, policy 13, disputes 8, bill explanation 7, treatment 6, entitlements 5, CSR runbook 9, revenue assurance and fraud 4, payments 3, VAS and plan 2. Five of the CSR runbook cases are troubleshooting turns (failed payment, unbar not applied, roaming not working, bill not generated, entitlement missing). CI scores those on the fake model. That is not a hosted-model measurement.

CI runs the harness inside pytest against the fake model. That smoke test checks that guardrail cases are refused, that no case calls an approve tool, and that a report file is written. It is not a quality score.

No measured run is committed. The table is a placeholder. Fill it by running the command below against a database seeded with the same `data/ground_truth.json`, then reading `reports/eval/report.md`.

| Metric | Fake smoke (CI) | Hosted model |
| --- | --- | --- |
| Cases | 72 | — |
| Fault detected | — | — |
| Credit amount correct | — | — |
| Accuracy | — | — |
| Tool-call correctness | — | — |
| Citation correctness | — | — |
| Refusal correctness | — | — |
| Cost (USD) | 0 | — |
| Latency p50 / p95 | — | — |

```bash
LLM_BACKEND=api LLM_API_KEY=sk-... LLM_BASE_URL=https://api.openai.com/v1 LLM_MODEL=gpt-4o-mini \
  python -m billpilot.evals --backend api --ground-truth data/ground_truth.json --output reports/eval
```

`reports/` is gitignored. Print the case counts and the cost line without calling a model:

```bash
python -m billpilot.evals --estimate-only --ground-truth data/ground_truth.json
```

**Cost estimate, not a measurement.** At the built-in `gpt-4o-mini` prices (0.15 USD per million prompt tokens, 0.60 USD per million completion tokens), one full run of 72 cases is **0.084240 USD**. The formula assumes 3 calls per case, 1200 prompt tokens and 350 completion tokens per call. Hash embeddings are free and are not in that number. A different model uses `LLM_PRICE_TABLE` or the `LLM_*_PRICE_PER_MILLION` fallbacks. The fake backend costs 0.

## Operations

Events are written to `outbox_events` in the same transaction as the API write. `EVENT_BACKEND=postgres` (the default, and the Render setting) is the queue: the consumer reads `pending` rows. `EVENT_BACKEND=redpanda` (Docker Compose) relays the same row to a single-node Redpanda after commit. Topics: `usage.rated`, `bill.run`, `payment.events`, `treatment.actions`, `entitlement.changes`, `provisioning.events`, `system.errors`. `provisioning.events` is extra to the deck list so a provisioning mismatch is not mixed with an entitlement change.

The consumer opens incidents for failed bill runs, failed payments and autopay, provisioning or entitlement mismatches, and dead-lettered events. A bill run still `started` after `STUCK_BILL_RUN_SECONDS` (900) becomes `stuck`. Poison events (`system.error.poison`) retry inside one consume pass and land on `dead_letter_events` with `retry_count` 3. `POST /ops/deadLetters/{id}/replay` is ops-only, idempotent, and audited once. `billpilot faults simulate` and `POST /ops/faults/simulate` emit the synthetic failures.

Reports (billing, collections and treatment, disputes and credits, payments, agent usage and cost) are SQL aggregates for the latest invoice day and that month. `billpilot reports generate` or **Generate reports** on `/ops` writes them. CSV is `GET /ops/reports/{id}/csv` and a download button that builds the file from the JSON.

Fraud and revenue checks are SQL. They do not read the answer key. A finding matches a planted anomaly when the account and the anomaly type are the same. Controls are not labels. Precision is matched findings divided by all findings. Recall is matched labels divided by labelled anomalies. On the small synthetic seed (48 customers, seed 42, one of each planted anomaly, plus the healthy controls) the measured precision is **1.0** and the measured recall is **1.0** (23 findings, 23 labelled anomalies, no false positives). Those numbers come from `tests/test_detectors.py` / `billpilot assurance score` against that seed's `ground_truth`. They are a measurement of the SQL checks, not a language-model score. `usage_without_charge` is a real check and finds no row on this generator, so it is not in the labelled set. Ops can open a case or, when the evidence has a positive pre-tax amount, propose a credit. The credit stays `pending_approval`. The ops actor that proposed it cannot approve it.

`POST /agent/troubleshoot` is CSR-only. The CSR pastes an error or a symptom. The agent returns numbered steps with a runbook citation, reads the account with the existing tools, and lists related incidents. The fake model covers this in CI. No hosted-model eval score is claimed for it.

```bash
billpilot faults simulate
billpilot consume
billpilot reports generate
billpilot assurance run
billpilot assurance score --ground-truth data/ground_truth.json
```

## Decisions

Short notes on why the obvious alternatives were not taken live in [docs/decisions](docs/decisions). Phase 2 notes cover the hosted model, hash embeddings, pgvector, HTTP tools, persona allowlists, propose-not-apply, guardrails, `agent_runs`, the fake model, the treatment read, and the fraud-flag read. Phase 3 notes cover the React UI, Render and Neon, per-step Langfuse traces (which replace the old on/off hook), and the credit approval queue. Sign-in notes cover the session cookie ([0024](docs/decisions/0024-signed-session-cookie.md)), the hand-built shell ([0025](docs/decisions/0025-enterprise-shell.md)), and the demo users ([0026](docs/decisions/0026-demo-users.md)). Phase 4 notes cover the two event backends ([0027](docs/decisions/0027-event-backends.md)), the failure store ([0028](docs/decisions/0028-failure-store.md)), SQL reports ([0029](docs/decisions/0029-sql-reports.md)), the rule detectors ([0030](docs/decisions/0030-rule-detectors.md)), and CSR troubleshooting ([0031](docs/decisions/0031-csr-troubleshooting.md)).

Ops still approves a credit on the existing endpoint. That audit row is where the approver, amount, and timestamp are recorded. The copilot's own audit row records the proposal (`decision=propose`), not an approver, because the copilot is never the approver.

## Roadmap

The deck's later phases were reordered. This is the plan the repo follows now.

| Phase | What it is | Status |
| --- | --- | --- |
| 1 | Postgres ledger, synthetic generator, TMF-shaped mock APIs, approval queue, audit log, Docker Compose, CI | Done, on `main` |
| 2 | Tool-calling copilot, RAG with citations, guardrails, propose-not-apply, eval harness | Done, on `main` |
| 3 | UI (customer portal, CSR console, ops control tower), sign-in and role scope, free-tier deploy, Langfuse tracing | Done, on `main` |
| 4 | Ops layer: Redpanda or a Postgres outbox, failure dashboard, SQL reports, fraud and revenue checks, CSR troubleshooting | This branch |
| 5 | Onboarding and migration: one API call, bulk dry run, reconciliation, idempotent re-runs, rollback | Not started |
| 6 | Integration and launch | Not started |

Still deferred inside those phases, not scheduled on their own: certified TM Forum conformance, split GST, and multi-replica rate limits. An approve tool stays out. Ops keeps the existing approval endpoint.
