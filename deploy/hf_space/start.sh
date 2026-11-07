#!/bin/sh
# One container runs the API and an RQ worker for the `cpu` queue (needs REDIS_URL, e.g. a free Upstash Redis).
set -e
cd /app/backend
mkdir -p "$DATA_DIR"
if [ -n "$REDIS_URL" ]; then
  python -m app.worker --queues cpu --kind cpu &
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" --proxy-headers
