#!/usr/bin/env sh
set -eu

if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
  alembic upgrade head
fi

if [ "${SEED_DEMO:-false}" = "true" ]; then
  python -m app.db.seed
fi

exec "$@"
