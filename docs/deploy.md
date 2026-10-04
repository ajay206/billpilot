# Deploy BillPilot on free tiers

This is a portfolio deploy. The data is synthetic. You create the accounts and click deploy. Nothing in this repository signs you up for a host.

The shape is one container (API and the built UI) plus a hosted Postgres that has pgvector. The choices and the reasons are in [0021](decisions/0021-render-and-neon.md).

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
