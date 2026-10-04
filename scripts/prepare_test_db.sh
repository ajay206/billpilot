#!/bin/sh
# Start the Compose Postgres and create the database pytest is allowed to use.
set -eu
docker compose up -d postgres
i=0
until docker compose exec -T postgres pg_isready -U billpilot -d billpilot >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 30 ]; then
    echo "Postgres did not become ready." >&2
    exit 1
  fi
  sleep 1
done
exists=$(docker compose exec -T postgres psql -U billpilot -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='billpilot_test'")
if [ "$exists" != "1" ]; then
  docker compose exec -T postgres psql -U billpilot -d postgres -c "CREATE DATABASE billpilot_test"
fi
