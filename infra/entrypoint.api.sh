#!/usr/bin/env bash
set -euo pipefail

# Run DB migrations then boot the API. Alembic is idempotent, so it is safe
# to run on every container start.
echo "[entrypoint] Running database migrations..."
alembic upgrade head

echo "[entrypoint] Starting API on ${API_HOST:-0.0.0.0}:${API_PORT:-8000}"
exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
