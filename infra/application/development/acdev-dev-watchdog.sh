#!/bin/bash
# Restart an acdev dev server when its pages fail for two minutes (orchestrator, 20-21 Oct 2026).
#
# Usage: acdev-dev-watchdog <unit> <url> [host-header]
#   acdev-dev-watchdog acdev-xray-dev.service http://127.0.0.1:3026/login salesxray-dev.authorityclosers.com
#
# On 20 Oct Turbopack hung compiling a new Admin route; on 21 Oct the Sales Xray dev server sat
# at its 3 GB MemoryHigh, throttled rather than killed, so systemd never restarted it. Both times
# every page answered 5xx or nothing until someone restarted the server by hand. This probe runs
# every 30 seconds from acdev's user timer acdev-dev-watchdog@<unit>.timer: a 5xx, no answer or a
# 20-second timeout starts a "bad since" clock; a good answer clears it; bad for 120 seconds
# restarts the unit, at most once every five minutes so a slow first compile after a restart is
# never cut short. A unit that is not active (stopped on purpose, or failed) is left alone. One
# journal line per restart, with the unit's memory. Read only otherwise: nothing outside its own
# state directory changes.
#
# Environment (tests): WATCHDOG_STATE_DIR, WATCHDOG_NOW (epoch seconds), WATCHDOG_CURL,
# WATCHDOG_SYSTEMCTL.
set -uo pipefail

if (( $# < 2 || $# > 3 )); then
  echo "usage: acdev-dev-watchdog <unit> <url> [host-header]" >&2
  exit 2
fi
unit="$1"
url="$2"
host="${3:-}"
[[ "$unit" == *.service ]] || unit="$unit.service"
if [[ ! "$unit" =~ ^[A-Za-z0-9@._-]+\.service$ || ! "$url" =~ ^https?:// ]]; then
  echo "acdev-dev-watchdog: bad unit or url: $unit $url" >&2
  exit 2
fi

state_dir="${WATCHDOG_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/acdev-dev-watchdog}/${unit%.service}"
now="${WATCHDOG_NOW:-$(date +%s)}"
curl_bin="${WATCHDOG_CURL:-curl}"
systemctl_bin="${WATCHDOG_SYSTEMCTL:-systemctl}"
bad_for=120
grace=300

mkdir -p "$state_dir" || exit 1
bad_file="$state_dir/bad-since"
restart_file="$state_dir/last-restart"

if ! "$systemctl_bin" --user is-active --quiet "$unit"; then
  rm -f -- "$bad_file"
  exit 0
fi

curl_args=(-s -o /dev/null -m 20 -w '%{http_code}')
[[ -n "$host" ]] && curl_args+=(-H "Host: $host")
code="$("$curl_bin" "${curl_args[@]}" "$url" 2>/dev/null)"
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

memory="$("$systemctl_bin" --user show -p MemoryCurrent --value "$unit" 2>/dev/null)"
if [[ "$memory" =~ ^[0-9]+$ ]]; then memory="$(( memory / 1048576 ))M"; else memory="unknown"; fi

printf '%s\n' "$now" > "$restart_file"
rm -f -- "$bad_file"
echo "acdev-dev-watchdog: $url answered $code for $(( now - since ))s (memory $memory); restarting $unit"
exec "$systemctl_bin" --user restart "$unit"
