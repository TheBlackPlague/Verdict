#!/bin/sh
set -eu

: "${VERDICT_SECRET_KEY:?Set VERDICT_SECRET_KEY to a persistent random secret}"
: "${VERDICT_DATA_DIR:=/data}"
export VERDICT_DATA_DIR
mkdir -p "$VERDICT_DATA_DIR/Media"

if [ "${1:-}" = "gunicorn" ]; then
    # These commands load Django too; do not start the background PGN watcher yet.
    VERDICT_DISABLE_WATCHER=1 python manage.py migrate --noinput
    VERDICT_DISABLE_WATCHER=1 python manage.py collectstatic --noinput
fi

# Gunicorn becomes PID 1 and receives Docker's shutdown signal directly.
exec "$@"
