#!/bin/bash
# AUT-2158: dev-only, dry-run by default. No settings changes or provider calls.
# --apply backs up each destination and restores it if startup/health fails.
# --rollback <backup-directory> restores that exact installation's prior state.
set -euo pipefail
umask 077
repo=$(cd "$(dirname "$0")/../../.." && pwd)
api=ac-dev-live-api.service
runner=ac-lead-desk-ai@development-live.service
worker=ac-dev-live-sales-xray-worker.service
backup_root=/var/lib/ac-dev-live-runners/AUT-2158
sources=(
  infra/application/development/ac-dev-live-api.service.d/zz-concurrency.conf
  infra/application/scripts/ac-lead-desk-ai
  infra/application/systemd/ac-lead-desk-ai@.service
)
targets=(
  /etc/systemd/system/ac-dev-live-api.service.d/zz-concurrency.conf
  /usr/local/sbin/ac-lead-desk-ai
  /etc/systemd/system/ac-lead-desk-ai@.service
)
[[ $EUID == 0 ]] || { echo "Run through ac-root" >&2; exit 77; }
exec 9>/run/ac-dev-live-backend.lock
flock -n 9 || { echo "Dev-live deploy is busy; no change" >&2; exit 75; }

restore() {
  local backup=$1 index
  [[ $backup == "$backup_root/"* && -f $backup/manifest ]] || return 64
  systemctl stop "$runner" || true
  if [[ $(cat "$backup/runner-enabled") != enabled ]]; then
    systemctl disable "$runner"
  fi
  for index in 0 1 2; do
    if [[ -f $backup/$index ]]; then
      cp -a "$backup/$index" "${targets[$index]}"
    else
      rm -f -- "${targets[$index]}"
    fi
  done
  systemctl daemon-reload
  systemctl restart "$api"
  if [[ $(cat "$backup/runner-active") == active ]]; then
    systemctl start "$runner"
  fi
  echo "Restored prior dev-only files from $backup"
}

if [[ ${1:-} == --rollback && $# == 2 ]]; then
  restore "$2"
  exit
fi
[[ $# == 0 || ( $# == 1 && $1 == --apply ) ]] || exit 64
systemctl is-active --quiet "$api" "$worker"
[[ $(systemctl show "$worker" -p Nice --value) == 10 ]]
bash -n "$repo/${sources[1]}"
slot=$(cat /var/lib/ac-dev-live-backend/active-slot)
[[ $slot == a || $slot == b ]]
python=/srv/authority-closers/development/live-backend/$slot/.venv/bin/python
cd /  # Do not import a moving checkout.
status=$(env -i PATH=/usr/local/bin:/usr/bin:/bin "$python" \
  -m ac_platform.lead_desk.ai_replies.cli \
  --service-config /etc/authority-closers/development/service-live.json \
  --database-url-file /etc/authority-closers/development/database-url-live)
printf '%s' "$status" | "$python" -c \
  'import json,sys; d=json.load(sys.stdin); assert d["enabled"] is False; print("Lead Desk AI dry-run: disabled; no provider call")'
for index in 0 1 2; do
  sha256sum "$repo/${sources[$index]}"
  echo "destination: ${targets[$index]}"
done
[[ ${1:-} == --apply ]] || { echo "Dry-run complete; no host files changed"; exit; }
changed=0
for index in 0 1 2; do
  cmp -s "$repo/${sources[$index]}" "${targets[$index]}" || changed=1
done
if [[ $changed == 0 ]] && systemctl is-active --quiet "$runner" && \
  systemctl is-enabled --quiet "$runner" && \
  [[ $(systemctl show "$api" -p Nice --value) == 0 ]]; then
  echo "Already installed and active; no restart"
  exit
fi
backup=$backup_root/$(date -u +%Y%m%dT%H%M%SZ)-$$
install -d -m 0700 "$backup"
printf '%s\n' "${targets[@]}" >"$backup/manifest"
systemctl is-enabled "$runner" >"$backup/runner-enabled" 2>/dev/null || true
systemctl is-active "$runner" >"$backup/runner-active" 2>/dev/null || true
for index in 0 1 2; do
  [[ ! -e ${targets[$index]} ]] || cp -a "${targets[$index]}" "$backup/$index"
done
echo "rollback-directory: $backup"
# code is assigned inside the trap body.
# shellcheck disable=SC2154
trap 'code=$?; trap - ERR; restore "$backup"; exit "$code"' ERR
install -d -m 0755 /etc/systemd/system/ac-dev-live-api.service.d
for index in 0 1 2; do
  mode=0644
  [[ $index != 1 ]] || mode=0755
  install -m "$mode" "$repo/${sources[$index]}" "${targets[$index]}"
done
systemd-analyze verify "${targets[2]}"
systemctl daemon-reload
systemctl restart "$api"
ready=0
for ((attempt=0; attempt<30; attempt++)); do
  if curl --fail --silent --max-time 2 -H 'Host: localhost' \
    http://127.0.0.1:8101/health/ready >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
[[ $ready == 1 ]]
[[ $(systemctl show "$api" -p Nice --value) == 0 ]]
[[ $(systemctl show "$worker" -p Nice --value) == 10 ]]
systemctl enable --now "$runner"
systemctl is-active --quiet "$api" "$worker" "$runner"
for index in 0 1 2; do
  cmp "$repo/${sources[$index]}" "${targets[$index]}"
done
trap - ERR
echo "Installed; API ready; background worker Nice=10; Lead Desk Admin unchanged"
