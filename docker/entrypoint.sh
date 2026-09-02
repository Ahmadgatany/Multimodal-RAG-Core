#!/bin/sh
set -eu

alembic upgrade head
exec gunicorn backend.app:app \
  --workers "${GUNICORN_WORKERS:-2}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 180
