#!/usr/bin/env bash
# Installs the production monitor's running copy on ac from this checkout (run as root, from the repo root):
#   sudo bash scripts/qa/monitor/install.sh [--enable]
# The files go to /home/acdev/qa-monitor (acdev's), the units to /etc/systemd/system. Without --enable the timer
# is installed but not started. Browser and Playwright are the nightly check's own (nothing is downloaded).
set -euo pipefail
ROOT=/home/acdev/qa-monitor
[ -f scripts/qa/monitor/monitor.mjs ] || { echo "run from the repo root" >&2; exit 2; }
install -d -o acdev -g acdev -m 750 "$ROOT" "$ROOT/state" "$ROOT/runs" "$ROOT/scripts/qa/monitor" "$ROOT/scripts/ci"
install -o acdev -g acdev -m 644 scripts/qa/monitor/monitor.mjs "$ROOT/scripts/qa/monitor/monitor.mjs"
install -o acdev -g acdev -m 755 scripts/qa/monitor/run.sh "$ROOT/scripts/qa/monitor/run.sh"
install -o acdev -g acdev -m 644 scripts/ci/wb_readability_lib.mjs "$ROOT/scripts/ci/wb_readability_lib.mjs"
[ -e "$ROOT/package.json" ] ||
  printf '%s\n' '{"private":true,"type":"module"}' | install -o acdev -g acdev -m 644 /dev/stdin "$ROOT/package.json"
[ -e "$ROOT/node_modules" ] || ln -s /home/acdev/qa-nightly/node_modules "$ROOT/node_modules"
install -o root -g root -m 644 scripts/qa/monitor/systemd/ac-qa-monitor.service /etc/systemd/system/ac-qa-monitor.service
install -o root -g root -m 644 scripts/qa/monitor/systemd/ac-qa-monitor.timer /etc/systemd/system/ac-qa-monitor.timer
systemctl daemon-reload
if [ "${1:-}" = "--enable" ]; then systemctl enable --now ac-qa-monitor.timer; fi
logger -t ac-qa "production monitor installed from $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
systemctl is-enabled ac-qa-monitor.timer 2>/dev/null || true
