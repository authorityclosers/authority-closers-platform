#!/bin/bash
# Restart Admin's dev server when its pages fail for two minutes (orchestrator, 20 Oct 2026).
#
# On 20 Oct Turbopack hung compiling a new route and every admin-dev page answered 5xx or
# nothing until someone restarted acdev-admin-dev by hand. This probe runs every 30 seconds
# from acdev's user timer: a 5xx, no answer or a 20-second timeout starts a "bad since"
# clock; a good answer clears it; bad for 120 seconds restarts the server, at most once every
# five minutes so a slow first compile after a restart is never cut short. One journal line
# per restart. Read only otherwise: nothing outside its own state file changes.
#
# Environment (tests): WATCHDOG_STATE_DIR, WATCHDOG_NOW (epoch seconds), WATCHDOG_CURL,
# WATCHDOG_SYSTEMCTL, WATCHDOG_URL, WATCHDOG_HOST.
set -uo pipefail

state_dir="${WATCHDOG_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/acdev-admin-dev-watchdog}"
now="${WATCHDOG_NOW:-$(date +%s)}"
curl_bin="${WATCHDOG_CURL:-curl}"
systemctl_bin="${WATCHDOG_SYSTEMCTL:-systemctl}"
url="${WATCHDOG_URL:-http://127.0.0.1:3028/login}"
host="${WATCHDOG_HOST:-admin-dev.authorityclosers.com}"
unit="acdev-admin-dev.service"
bad_for=120
grace=300

mkdir -p "$state_dir" || exit 1
bad_file="$state_dir/bad-since"
restart_file="$state_dir/last-restart"

code="$("$curl_bin" -s -o /dev/null -m 20 -w '%{http_code}' -H "Host: $host" "$url" 2>/dev/null)"
code="${code:-000}"

case "$code" in
  5??|000) ;;
  *)
    rm -f -- "$bad_file"
    exit 0
    ;;
esac

if [[ ! -s "$bad_file" ]]; then
  printf '%s\n' "$now" > "$bad_file"
  exit 0
fi
since="$(head -c 20 "$bad_file")"
[[ "$since" =~ ^[0-9]+$ ]] || since="$now"
(( now - since >= bad_for )) || exit 0

last=0
if [[ -s "$restart_file" ]]; then
  last="$(head -c 20 "$restart_file")"
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
fi
(( now - last >= grace )) || exit 0

printf '%s\n' "$now" > "$restart_file"
rm -f -- "$bad_file"
echo "acdev-admin-dev-watchdog: pages answered $code for $(( now - since ))s; restarting $unit"
exec "$systemctl_bin" --user restart "$unit"
