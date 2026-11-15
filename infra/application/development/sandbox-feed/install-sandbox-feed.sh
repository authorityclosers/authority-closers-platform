#!/bin/bash
# Installs the dev AC Sales Sandbox live feed on ac (DEV ONLY). Dry run by default;
# --apply copies the feed, its avatar drawer and the sandbox generator it builds on to
# /usr/local/lib/ac-dev-sandbox-feed, the one-off runner to /usr/local/sbin, the units to
# /etc/systemd/system, and enables the timer. --remove stops and removes all of it.
set -euo pipefail
umask 022
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
here=infra/application/development/sandbox-feed
lib=/usr/local/lib/ac-dev-sandbox-feed
sources=(
  scripts/sandbox_feed/feed.py
  scripts/sandbox_feed/avatars.py
  scripts/sandbox_feed/reports.py
  scripts/data-changes/sandbox-organisations.py
  "$here/python-path"
  "$here/ac-dev-sandbox-feed"
  "$here/ac-dev-sandbox-feed.service"
  "$here/ac-dev-sandbox-feed.timer"
)
targets=(
  "$lib/feed.py"
  "$lib/avatars.py"
  "$lib/reports.py"
  "$lib/sandbox-organisations.py"
  "$lib/python-path"
  /usr/local/sbin/ac-dev-sandbox-feed
  /etc/systemd/system/ac-dev-sandbox-feed.service
  /etc/systemd/system/ac-dev-sandbox-feed.timer
)
modes=(0644 0644 0644 0644 0755 0755 0644 0644)
[[ $EUID == 0 ]] || { echo "Run as root" >&2; exit 77; }
if [[ ${1:-} == --remove ]]; then
  systemctl disable --now ac-dev-sandbox-feed.timer || true
  rm -f -- "${targets[@]}"
  rmdir "$lib" 2>/dev/null || true
  systemctl daemon-reload
  echo "Removed"
  exit
fi
[[ $# == 0 || ( $# == 1 && $1 == --apply ) ]] || exit 64
grep -q '^AC_ENVIRONMENT="development"$' /etc/authority-closers/development/api-live.env
for index in "${!sources[@]}"; do
  [[ -f $repo/${sources[$index]} ]]
  sha256sum "$repo/${sources[$index]}" | cut -c1-16 | tr '\n' ' '
  echo "-> ${targets[$index]}"
done
[[ ${1:-} == --apply ]] || { echo "Dry run: nothing changed"; exit; }
install -d -m 0755 "$lib"
for index in "${!sources[@]}"; do
  install -m "${modes[$index]}" -o root -g root "$repo/${sources[$index]}" "${targets[$index]}"
done
systemctl daemon-reload
systemctl enable --now ac-dev-sandbox-feed.timer
systemctl list-timers ac-dev-sandbox-feed.timer --no-pager
