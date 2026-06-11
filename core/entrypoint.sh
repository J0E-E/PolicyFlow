#!/bin/sh
# Core service entrypoint: migrate -> seed placeholder -> serve.
#
# set -e makes any failure (including `alembic upgrade head`) exit non-zero, so
# the container fails its boot rather than serving a half-migrated app
# (stakeholder decision: migrate failure -> fail boot).
set -e

# Apply database migrations up to the latest revision.
alembic upgrade head

# Run the seed placeholder (the seam P1.8 fills).
python -m app.seed

# Hand off to the CMD (uvicorn) so it becomes PID 1's child and receives signals.
exec "$@"
