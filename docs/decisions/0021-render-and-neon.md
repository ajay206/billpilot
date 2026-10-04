# Render free web service and Neon Postgres

## Decision

Production, for this portfolio, is one Docker image on a Render free web service and a Neon free Postgres database. The image migrates on boot and seeds the synthetic ledger only when `customers` is empty. Render's health check is `GET /health`. `render.yaml` is the blueprint. `docs/deploy.md` is the click-path. This repository does not create the accounts.

The hosted seed is smaller than `docker compose up`: 48 customers, 2 months, one of each planted fault. Compose stays at 500 customers and 6 months.

The image installs the Python package, so paths next to `site-packages` are not the repo. The process working directory (`/app`) holds `docs/knowledge` and `web/dist`. Startup looks there when the checkout-relative path is missing.

## Alternatives

- Render Postgres. The free database expires about 30 days after creation, so a portfolio link would die. Neon does not work that way, and it has pgvector.
- Supabase. Also a hosted Postgres with pgvector. Neon was the smaller moving part: a database only, no extra auth product to turn off.
- Koyeb's free database. The published free allowance is a few hours of compute a month, which will not hold a demo that people open more than once.
- Fly.io. The reliable free allowance is gone. A deploy that might start billing is the wrong default for this repo.
- A second static host for the UI. Two cold starts, two URLs, and a CORS story, to serve files the API can serve itself.

## Why

The free web service sleeps, which is how 750 instance hours cover a month, and it wakes on the next request. Neon scales to zero when idle and already supports `CREATE EXTENSION vector`, which migration `002_agent` runs. One container means the persona UI and the API share an origin, so the demo keys travel as a header and not as a cross-site workaround. The smaller hosted seed is what fits a 512 MB instance and a first boot that has to finish before Render gives up on the port.
