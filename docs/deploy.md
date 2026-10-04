# Deploy BillPilot on free tiers

This is a portfolio deploy. The data is synthetic. You create the accounts and click deploy. Nothing in this repository signs you up for a host.

The shape is one container (API and the built UI) plus a hosted Postgres that has pgvector. The choices and the reasons are in [0021](decisions/0021-render-and-neon.md).

## How to test locally

You can do this on a laptop before you create any host account. Docker is the only install. The copilot stays on the scripted model until you set a key, so this costs nothing.

### A smaller ledger when RAM is tight

`docker compose up` with no overrides seeds **500 customers and 6 months**. That is the design target. On a laptop with limited free memory, use the same smaller ledger the free host uses: 48 customers, 2 months, one of each planted fault. Postgres plus that seed fits a machine that would struggle with the full set.

If a previous run already created the volume, remove it first. Otherwise the old 500-customer database is reused and the new counts are ignored.

```bash
docker compose down -v
```

Copy `.env.example` to `.env` and set these three lines. The anomaly JSON must name every fault type. `CUSTOMER_COUNT=48` is enough for one of each plus the healthy controls. It is not enough for the default counts, which need at least 112 customers.

```bash
CUSTOMER_COUNT=48
MONTHS=2
ANOMALY_COUNTS={"double_charge":1,"roaming_spike":1,"wrong_rate":1,"missed_discount":1,"charge_after_cancellation":1,"vas_not_opted_in":1,"payment_not_recorded":1,"payment_not_posted":1,"unbilled_usage":1,"duplicate_usage":1,"sim_swap":1,"barred_after_paying":1,"treated_during_open_dispute":1,"payment_not_ending_treatment":1,"promise_to_pay_ignored":1,"exempt_account_treated":1,"addon_never_activated":1,"allowance_not_reset":1,"overlapping_packs_double_counted":1,"overlapping_packs_dropped":1,"promo_ended_early":1,"feature_active_after_cancellation":1,"overage_on_covered_usage":1}
```

Leave `LLM_BACKEND=fake` and leave `LLM_API_KEY` empty.

```bash
docker compose up --build
```

Wait until the API log says it is listening, or until `curl -s http://localhost:8000/health` returns `"status":"ok"` and `"demoMode":true`. The first boot migrates and seeds. A later `docker compose up` skips the seed when `customers` already has rows.

If the seed container is killed before it prints `Seeded`, the machine ran out of memory. Run `docker compose down -v` and use the 48-customer settings above. Do not raise `CUSTOMER_COUNT` on a 512 MB host. That limit is the Render free instance, not your laptop.

### URLs and demo keys

| View | URL | Key the switcher sends | Scope |
| --- | --- | --- | --- |
| Customer | http://localhost:8000/customer (also http://localhost:8000) | `dev-customer-key` | `CUST-000001` only |
| CSR | http://localhost:8000/csr | `dev-csr-key` | Accounts assigned to `CSR-A`, including `CUST-000001` |
| Ops | http://localhost:8000/ops | `dev-ops-key` | Every account, approvals, runs, audit. No customer chat |
| Health | http://localhost:8000/health | none | `demoMode` and `tracing` |
| API docs | http://localhost:8000/docs | none | OpenAPI |

The keys are the published demo defaults. They are in the frontend bundle on purpose. Do not replace them with a key you care about.

### Click-through

The banner should say **Demo mode** before you start.

**Customer** at http://localhost:8000/customer

1. Confirm the rail shows `CUST-000001` and a latest bill.
2. Click **Why is my bill higher this month? Explain it line by line.** Wait for the answer. It names the bill and the lines.
3. Click a citation chip, such as `billing-policy.md` or `tariffs.md`. A drawer opens that policy section. Close it.
4. Click **What are the roaming rules for charges outside the home network?** The answer cites `roaming.md`. Open that chip.
5. Click **I think I was charged twice. Please open a dispute.** The rail shows the dispute with status `open`. A customer cannot apply a credit. The answer says a CSR has to propose one and ops has to approve it.
6. Click **What are the refund, deposit, and porting rules?** and **Did I opt into a value-added service, and what plan am I on?** Each answer cites a policy section.

**CSR** at http://localhost:8000/csr

1. Search `CUST-000001` and select that account.
2. Walk the tabs: Bills, Lines, Usage, Payments, Treatment, Tickets, Disputes. Disputes shows the dispute from the customer step, with status `open`.
3. In the copilot box, ask: `Explain the latest bill line by line against the tariff.`
4. Open the **tool calls** control under the answer. You should see the bill, the lines, and a policy search. Click a citation chip and read the section.
5. The **CSR troubleshooting AI** panel says Phase 4. It does not take an error paste yet.

`CUST-000001` is the healthy demo customer. The copilot proposes a credit only when it finds a duplicate line, and it will not auto-credit a roaming spike. On the 500-customer seed, search `CUST-000003` (even index, so CSR-A can see it) and ask: `I think this bill was charged twice. Propose a credit. Do not apply it.` The card says **Pending approval**. On the 48-customer seed the only double charge is `CUST-000002`, which belongs to CSR-B. To watch the copilot propose that one, set `CSR_CODE=CSR-B` in `.env`, run `docker compose up -d --force-recreate api`, and search `CUST-000002` with the same question. Set `CSR_CODE` back to `CSR-A` when you are done.

To put a credit on the demo account without hunting for a planted fault, propose one with the CSR key. It stays `pending_approval`. Replace `ACCOUNT_ID` and `BILL_ID` with the ids from the CSR Bills tab (or from the customer bill API).

```bash
curl -s -X POST http://localhost:8000/tmf-api/customerBillManagement/v4/billAdjustment \
  -H 'X-API-Key: dev-csr-key' -H 'Content-Type: application/json' \
  -d '{"billingAccount":{"id":"ACCOUNT_ID"},"customerBill":{"id":"BILL_ID"},"adjustmentType":"credit","amount":{"unit":"INR","value":"10.00"},"reason":"Demo credit, still pending approval."}'
```

**Ops** at http://localhost:8000/ops

1. Confirm the page says ops has no customer chat. The three counters are open disputes, pending approvals, and fraud flags.
2. On **Credits**, the proposed credit shows the amount, the reason, and who proposed it. Click **Approve**. The notice names the approver (`ops`) and the status. The row leaves the pending list. Reload the customer view: the credit is no longer pending, and the line names who decided it.
3. A second `POST` to `/tmf-api/customerBillManagement/v4/billAdjustment/{id}/approve` returns 409 and does not change the bill again. The UI shows that message when the endpoint returns 409.
4. Open **Unbars** and **Plan changes**. Both say there is no proposal and no endpoint. Do not expect a button there.
5. **Recent agent runs** lists the turns you just made, with decision, token total, estimated cost, latency, and trace id. The trace id is a dash until Langfuse keys are set.
6. **Audit log** lists the chat turns and the approval. The request column is the first characters of the request id.
7. **Failure dashboard** and **Reports** are marked Phase 4, including fraud and revenue checks.

### Switch from the fake model to a real API key

Still local. Put the key only in `.env`, which is gitignored.

```bash
LLM_BACKEND=api
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

Any host that accepts `POST {LLM_BASE_URL}/chat/completions` works. Keep `EMBEDDING_BACKEND=hash` so you are not billed for vectors.

Recreate the API so it reads the new values. The database volume stays.

```bash
docker compose up -d --build api
```

Reload http://localhost:8000/health. `demoMode` is false and `llmBackend` is `api`. The banner no longer says demo mode. Ask one customer question and stop. Each question spends tokens on your key.

To go back, set `LLM_BACKEND=fake`, clear `LLM_API_KEY`, and run `docker compose up -d --build api` again. `demoMode` returns to true.

## What you create

| Account | Plan | Pays for |
| --- | --- | --- |
| [Neon](https://neon.tech) | Free | Postgres 16 with the `vector` extension. Compute scales to zero after a few idle minutes. |
| [Render](https://render.com) | Free web service | The Docker image. 512 MB RAM. Spins down after inactivity. 750 free instance hours per workspace each month. |
| A model host, optional | Usage-priced | Any OpenAI-compatible `/chat/completions` API. Leave it unset and the app stays in demo mode. |
| [Langfuse Cloud](https://cloud.langfuse.com) | Hobby | Traces. Free, no card. 50k units a month, 30 days of retention, 2 users. Confirm the current numbers on [their pricing page](https://langfuse.com/pricing) before you rely on them. |

Free tiers change. If a limit on this page disagrees with the vendor's page, trust the vendor.

## 1. Neon database

1. Create a Neon account and a project. Pick a region close to the Render region in `render.yaml` (Singapore, unless you change it).
2. The Postgres version should be 16. pgvector is available. You do not create the extension yourself. The migration runs `CREATE EXTENSION vector` on first boot.
3. Copy the **direct** connection string, not the pooled one. Migrations and pgvector are happier without the pooler. It looks like `postgresql://USER:PASSWORD@ep-….aws.neon.tech/neondb?sslmode=require`.
4. The app rewrites `postgresql://` to `postgresql+psycopg://` and keeps `sslmode`. Paste the string as Neon shows it.

A free project suspends compute after it sits idle (Neon documents about five minutes). The next request waits for it to wake, on top of the Render cold start.

## 2. Render web service

1. Push this branch, or merge it, so Render can see `render.yaml` and the Dockerfile.
2. In the Render dashboard, create a Blueprint and point it at the repository. It reads `render.yaml` and proposes one free web service named `billpilot`.
3. When it asks for secret env vars, set:
   - `DATABASE_URL` — the Neon string from step 1.
   - `LLM_API_KEY` — leave blank for demo mode.
   - `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` — leave blank until step 4. If you set them, `LANGFUSE_HOST` is `https://cloud.langfuse.com` for Langfuse Cloud.
4. Confirm the plan is **Free**. Apply the blueprint.

The container migrates, and if `customers` is empty it seeds, then listens on the port Render assigns. `/health` must return 200. The first boot is the slow one: it loads the synthetic ledger (48 customers, 2 months, one of each planted fault, so it fits a 512 MB instance). Later boots see the rows and skip the seed.

Open `https://<your-service>.onrender.com`. The three persona buttons use `dev-customer-key`, `dev-csr-key`, and `dev-ops-key`. Those values are also set in `render.yaml`. They are the published demo keys, not a production secret. Do not replace them with a key you care about and leave it in the frontend. The UI has those three strings baked in. A real model key stays in `LLM_API_KEY` on the server and never in the bundle.

### Demo mode and a real model

With `LLM_BACKEND=fake` (the blueprint default) or with `LLM_API_KEY` empty, the banner says **Demo mode**. The copilot is the scripted model. No key, no spend.

To use a hosted model, set in the Render dashboard (not in git):

```text
LLM_BACKEND=api
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

Any host that accepts `POST {LLM_BASE_URL}/chat/completions` works. Redeploy after saving the env vars. The banner changes and the demo-mode line goes away. Embeddings stay on `EMBEDDING_BACKEND=hash` so you are not billed for vectors.

### Cold starts and other limits

- Render's free web service sleeps when nobody is calling it. The next visit waits while the container starts. Budget half a minute, sometimes longer, and longer still if Neon was asleep.
- The free instance has 512 MB of RAM and a small CPU share. That is why the hosted seed is 48 customers, not the 500 used by `docker compose up`. Raise `CUSTOMER_COUNT` only after a boot succeeds. The generator refuses a count that cannot hold the demo customer, every planted fault, and the healthy controls.
- There is no persistent disk. `data/ground_truth.json` is written to `/tmp` and disappears on the next deploy. The ledger in Neon does not.
- 750 free instance hours per workspace per month is the published Render allowance. One always-on service would not fit in a month once you count the hours it is awake. Sleeping is what keeps it inside the allowance.
- Render's own free Postgres expires about 30 days after creation. This blueprint does not use it. Neon is the database.
- Rate limits are per process. One free instance is one process, so that matches.

If the first deploy fails before `/health` answers, open the Render logs. A seed error or a bad `DATABASE_URL` exits before the port opens. Fix the env var and redeploy. You do not need to wipe Neon. An empty `customers` table is seeded again. A partial seed is not detected: if `customers` has rows, boot will not re-seed. To start over, drop the Neon database (or the tables) and redeploy.

## 3. Langfuse Cloud Hobby

1. Create a Langfuse Cloud account and a project. The Hobby plan does not ask for a card.
2. In the project settings, create API keys. You get a public key and a secret key.
3. Set these on the Render service:

```text
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

4. Redeploy. `GET /health` then includes `"tracing": true`.

Each copilot turn is one trace named `billpilot.chat`. Inside it: a guardrail span, a generation for each model call (tokens and estimated cost), a tool span per call, a retriever span whose output lists the cited doc ids, an output-check span, and a decision span (`read`, `advise`, `propose`, or `refuse`). The trace id is stored on `agent_runs.trace_id` and shown in the ops dashboard.

If Langfuse is down, or a key is wrong, the chat still answers. The failure is logged and swallowed. Leave any of the three variables empty and tracing is a no-op. That is what CI and `docker compose up` do.

A turn with several tool calls is several billable units (the trace plus each observation), not one. Hobby includes 50k units a month and keeps data for 30 days, with 2 users, as published on the pricing page. A portfolio demo will not get near that. Self-hosting Langfuse is a different project and is not part of this deploy.

## 4. Check that it works

1. `https://<service>.onrender.com/health` returns `status: ok` and `demoMode: true` until you set a model key.
2. The customer view loads `CUST-000001` and can answer a roaming question with a citation you can open.
3. The CSR view can search that customer and shows tool calls after a turn.
4. The ops view shows the approval queue, recent runs, and the audit log. Approving a credit uses the existing endpoint. A second approve returns 409 and the bill does not change again.
5. After Langfuse is configured, the ops run row shows a trace id. The same id is in the Langfuse project.

Local `docker compose up` is the same image shape: Postgres in Compose, the API serving the UI on port 8000, seed on first boot of an empty database. See the README quickstart.
