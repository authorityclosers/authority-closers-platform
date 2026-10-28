#!/usr/bin/env bash
set -euo pipefail
cd "${HOME}/rehearsal/application"
[[ -f ../FICTIONAL-ONLY ]] || { echo 'Missing isolated rehearsal marker' >&2; exit 1; }
exec docker compose --env-file ../runtime.env --project-name ac-rehearsal \
  -f compose.yaml -f compose.filesystem-media.yaml -f compose.sales-xray-hosted-openai.yaml \
  -f compose.production-lean.yaml -f compose.rehearsal.yaml --profile sales-xray-hosted "$@"
