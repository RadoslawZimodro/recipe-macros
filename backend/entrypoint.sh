#!/bin/sh
set -e

# Bring the schema up to date before serving requests.
alembic upgrade head

exec "$@"
