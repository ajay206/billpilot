#!/bin/sh
set -eu
billpilot migrate
exec uvicorn billpilot.main:app --host 0.0.0.0 --port 8000
