#!/bin/sh
set -eu

uv run --no-sync alembic upgrade head
exec "$@"

