# BillPilot

BillPilot is an AI copilot for telecom billing and operations. Phase 1 is the mock billing system: a PostgreSQL ledger of synthetic customers, and a FastAPI service whose resources are shaped like TM Forum Open APIs. Phase 2 is the copilot: a tool-calling agent, a small policy corpus, an audit row per turn, a CLI, `POST /agent/chat`, and an evaluation harness.

There is still no message broker and no user interface. Money and service changes stay on the Phase 1 approval queue. The copilot proposes a credit. It cannot apply one.

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
  subgraph later [Later]
    UI[UI]
    Broker[Kafka]
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
  UI -.-> API
  API -.-> Broker
```

The database is the system of record. The API translates internal words (`issued`, `posted`, `soft_bar`) into TMF-like words (`sent`, `done`, a trouble-ticket status). Writes that move money start as `pending_approval`. A different role applies them. Every write, including a copilot turn, is appended to `audit_log`.

The copilot does not query the billing tables. Its tools call the HTTP API with the caller's key. Policy text is the exception: `docs/knowledge/` is embedded into `knowledge_chunks` and searched in process. A turn is stored on `agent_runs` and linked to the audit row. Design notes for each of those choices are in [docs/decisions](docs/decisions).

## Quickstart

Requirements: Docker, and for tests a local Python 3.12.

```bash
docker compose up --build
```

That starts Postgres, runs migrations, and seeds 500 customers across 6 months. The API is at <http://localhost:8000/docs>.

Persona keys (local demo defaults, also in `.env.example`):

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

The image migrates on startup and does not load the synthetic ledger by itself. This Compose file uses the published image for both the one-shot seed and the API:

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
    ports:
      - "8000:8000"
```

### Tests

```bash
pip install -e ".[dev]"
make test
```

`make test` starts Postgres, creates a database named `billpilot_test`, then runs ruff and pytest. Tests refuse any other database name.

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
| GET | `/ops/auditLog` | ops |
| POST | `/agent/chat` | the API key chooses the persona; body is `message` and optional `accountId` |
| GET | `/health` | public |

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

Langfuse is off. Set `LANGFUSE_ENABLED=true` and install the extra with `pip install -e ".[tracing]"` only if you want traces. A missing package or a failed export does not change the answer.

### Ask

Start the stack, then:

```bash
billpilot ask --persona customer "Explain my latest bill, line by line, against last month and the tariff."
```

CSR and ops need an account id. Planted faults alternate assignees: even indexes are `CSR-A`, odd indexes are `CSR-B` (`assigned_csr` is `CSR-A` when `index % 2 == 0`). The first anomaly is index 1, so a double charge is `CSR-B`. The default `CSR_CODE` is `CSR-A` and will not see that account. For a manual CSR session on an odd-index fault, set `CSR_CODE=CSR-B` and use the CSR key. The eval harness rebinds the CSR code per case, so you do not set this for `python -m billpilot.evals`.

The same turn is `POST /agent/chat` with the persona's `X-API-Key`. The body cannot pick a different persona.

A credit proposal stays `pending_approval`. Ops approves it with the existing endpoint:

```bash
curl -s -X POST -H 'X-API-Key: dev-ops-key' -H 'Content-Type: application/json' \
  -d '{"decision":"approve"}' \
  http://localhost:8000/tmf-api/customerBillManagement/v4/billAdjustment/<id>/approve
```

### Evals

The harness builds 67 labelled cases from `data/ground_truth.json` (or from the generator if that file is missing). Counts: guardrail 15, policy 13, disputes 12, bill explanation 7, treatment 6, entitlements 5, CSR runbook 4, payments 3, VAS and plan 2.

CI runs the harness inside pytest against the fake model. That smoke test checks that guardrail cases are refused, that no case calls an approve tool, and that a report file is written. It is not a quality score.

No measured run is committed. The table is a placeholder. Fill it by running the command below against a database seeded with the same `data/ground_truth.json`, then reading `reports/eval/report.md`.

| Metric | Fake smoke (CI) | Hosted model |
| --- | --- | --- |
| Cases | 67 | — |
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

**Cost estimate, not a measurement.** At the built-in `gpt-4o-mini` prices (0.15 USD per million prompt tokens, 0.60 USD per million completion tokens), one full run of 67 cases is **0.078390 USD**. The formula assumes 3 calls per case, 1200 prompt tokens and 350 completion tokens per call. Hash embeddings are free and are not in that number. A different model uses `LLM_PRICE_TABLE` or the `LLM_*_PRICE_PER_MILLION` fallbacks. The fake backend costs 0.

## Decisions

Short notes on why the obvious alternatives were not taken live in [docs/decisions](docs/decisions). Phase 2 notes cover the hosted model, hash embeddings, pgvector, HTTP tools, persona allowlists, propose-not-apply, guardrails, `agent_runs`, the fake model, optional Langfuse, and the treatment read.

## Deferred

- Kafka (or Redpanda) and a consumer for failed downstream work. `NullPublisher` is the stand-in. Topics already named: `usage.rated`, `bill.run`, `payment.events`, `treatment.actions`, `entitlement.changes`, `system.errors`.
- Dashboards, onboarding, and bulk migration.
- A user interface.
- Certified TM Forum conformance, split GST, and multi-replica rate limits.
- An approve tool. Ops keeps the existing approval endpoint. The copilot must not be the approver.
