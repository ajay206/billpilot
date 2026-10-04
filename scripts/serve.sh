#!/bin/sh
set -eu
billpilot migrate
billpilot seed-if-empty
exec uvicorn billpilot.main:app --host 0.0.0.0 --port 8000
