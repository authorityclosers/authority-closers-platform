#!/usr/bin/env bash
# Install the usage metrics collector from this checkout (run as root on the ac host).
# Usage: install.sh [--dev-api]
#   --dev-api also lets the dev-live API read the dev and staging exports.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
install -d -m 0755 /usr/local/lib/ac-metrics /srv/authority-closers/metrics
install -m 0644 "$here/usage-metrics-export.sql" /usr/local/lib/ac-metrics/usage-metrics-export.sql
sha256sum "$repo"/packages/python/ac_platform/conversation_intelligence/canary_fixture/*.wav \
  | awk '{print $1}' > /usr/local/lib/ac-metrics/canary-fixtures.txt
git -c safe.directory="$repo" -C "$repo" rev-parse HEAD > /usr/local/lib/ac-metrics/SOURCE_SHA 2>/dev/null || true
install -m 0755 "$here/ac-metrics-collect" /usr/local/sbin/ac-metrics-collect
install -m 0755 "$here/ac-budget-alerts" /usr/local/sbin/ac-budget-alerts
install -m 0755 "$here/ac-agent-burn" /usr/local/sbin/ac-agent-burn
install -m 0755 "$here/ac-cost-detect" /usr/local/sbin/ac-cost-detect
install -m 0644 "$here/ac-metrics-collect.service" "$here/ac-metrics-collect.timer" \
  "$here/ac-agent-burn.service" "$here/ac-agent-burn.timer" \
  "$here/ac-cost-detect.service" "$here/ac-cost-detect.timer" \
  "$here/ac-cost-detect-billing.service" "$here/ac-cost-detect-billing.timer" /etc/systemd/system/
if [ "${1:-}" = "--dev-api" ]; then
  install -d -m 0755 /etc/systemd/system/ac-dev-live-api.service.d \
    /srv/authority-closers/metrics/development /srv/authority-closers/metrics/staging
  install -m 0644 "$here/ac-dev-live-api.metrics-store.conf" \
    /etc/systemd/system/ac-dev-live-api.service.d/zz-metrics-store.conf
fi
systemctl daemon-reload
# ac-cost-detect does nothing until its service-account key exists (ConditionPathExists).
systemctl enable --now ac-metrics-collect.timer ac-agent-burn.timer ac-cost-detect.timer \
  ac-cost-detect-billing.timer
systemctl start ac-metrics-collect.service
