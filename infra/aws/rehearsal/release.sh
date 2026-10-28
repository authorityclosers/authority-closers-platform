#!/usr/bin/env bash
# Measured stop/migrate/recreate skeleton of today's installer, not a release engine.
set -euo pipefail
[[ -f "${HOME}/rehearsal/FICTIONAL-ONLY" ]] || exit 1
compose="${HOME}/rehearsal/compose.sh"
echo "release-start $(date -u +%FT%TZ)"
"$compose" stop --timeout 30 api worker
"$compose" stop --timeout 30 sales-xray-worker
"$compose" --profile release run --rm migrate
"$compose" up -d --no-deps --force-recreate --wait --wait-timeout 120 api
"$compose" up -d --no-deps --wait --wait-timeout 120 worker sales-xray-worker
echo "release-end $(date -u +%FT%TZ)"
