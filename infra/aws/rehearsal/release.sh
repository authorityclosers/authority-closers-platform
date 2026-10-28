#!/usr/bin/env bash
# Measured stop/migrate/recreate skeleton of today's installer, not a release engine.
set -euo pipefail
[[ -f "${HOME}/rehearsal/FICTIONAL-ONLY" ]] || exit 1
compose="${HOME}/rehearsal/compose.sh"
root="${HOME}/rehearsal"
cp "$root/application/Caddyfile" "$root/application/Caddyfile.serving"
cat "$root/application/release-hold.Caddyfile" > "$root/application/Caddyfile"
docker exec ac-rehearsal-caddy-1 caddy reload --address unix//tmp/caddy-admin.sock \
  --config /etc/caddy/Caddyfile --adapter caddyfile
echo "release-start $(date -u +%FT%TZ)"
"$compose" stop --timeout 30 api worker
"$compose" stop --timeout 30 sales-xray-worker
"$compose" --profile release run --rm migrate
"$compose" up -d --no-deps --force-recreate --wait --wait-timeout 120 api
"$compose" up -d --no-deps --wait --wait-timeout 120 worker sales-xray-worker
cat "$root/application/Caddyfile.serving" > "$root/application/Caddyfile"
docker exec ac-rehearsal-caddy-1 caddy reload --address unix//tmp/caddy-admin.sock \
  --config /etc/caddy/Caddyfile --adapter caddyfile
echo "release-end $(date -u +%FT%TZ)"
