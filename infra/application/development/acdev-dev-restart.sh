#!/bin/bash
# Nightly restart of an acdev dev server that clears its Turbopack cache above a size cap (21 Oct 2026).
#
# Usage: acdev-dev-restart <unit> <cache-dir> <cap-MiB> [<url> [<host-header>]]
#   acdev-dev-restart acdev-xray-dev.service \
#     ~/src/dev-live/authority-closers-platform/apps/sales-xray-web/.next/dev/cache/turbopack 2048 \
#     http://127.0.0.1:3026/login salesxray-dev.authorityclosers.com
#
# next dev 16.3.8 keeps a Turbopack file-system cache that nothing prunes. Sales Xray's grew to 9.6 GB
# between 11 and 21 Oct, about 2 GB on a busy day. Restoring and compacting it took the server to its
# 3 GB MemoryHigh, where the kernel throttles instead of killing, and took HMR from 0.5 s (p50, 11 Oct)
# to 13-38 s (18-20 Oct). This runs from the unit's nightly timer: it notes the memory peak, pauses the
# unit's watchdog (acdev-dev-watchdog@<unit>.timer), stops the unit, moves the cache aside when it is
# above the cap, starts the unit, waits for the probe page (the first compile), resumes the watchdog
# and then deletes the old cache. The cache is a build cache that next dev rebuilds; nothing else is
# ever moved or deleted. A unit stopped on purpose (inactive) stays stopped; a failed one is started.
# A watchdog that was not running stays off. One journal line per run.
#
# Environment (tests): RESTART_SYSTEMCTL, RESTART_CURL, RESTART_SLEEP, RESTART_NOW (epoch seconds),
# RESTART_WARMUP_TRIES (default 60, 5 seconds apart).
set -uo pipefail
shopt -s nullglob

if (( $# < 3 || $# > 5 )); then
  echo "usage: acdev-dev-restart <unit> <cache-dir> <cap-MiB> [<url> [<host-header>]]" >&2
  exit 2
fi
unit="$1"
cache="${2%/}"
cap="$3"
url="${4:-}"
host="${5:-}"
[[ "$unit" == *.service ]] || unit="$unit.service"
if [[ ! "$unit" =~ ^[A-Za-z0-9@._-]+\.service$ || ! "$cache" =~ ^/.+/\.next/dev/cache/turbopack$ ||
  "$cache" == *"/../"* || "$cache" == *"/./"* || ! "$cap" =~ ^[0-9]+$ ||
  ( -n "$url" && ! "$url" =~ ^https?:// ) ]]; then
  echo "acdev-dev-restart: bad unit, cache dir, cap or url: $*" >&2
  exit 2
fi
if [[ -L "$cache" ]]; then
  echo "acdev-dev-restart: $cache is a symlink; left alone" >&2
  exit 2
fi

systemctl_bin="${RESTART_SYSTEMCTL:-systemctl}"
curl_bin="${RESTART_CURL:-curl}"
sleep_bin="${RESTART_SLEEP:-sleep}"
tries="${RESTART_WARMUP_TRIES:-60}"
now="${RESTART_NOW:-$(date +%s)}"
watchdog="acdev-dev-watchdog@${unit%.service}.timer"

mib() { if [[ "$1" =~ ^[0-9]+$ ]]; then echo "$(( $1 / 1048576 ))M"; else echo "unknown"; fi; }
delete_old() {
  local old=("$cache".old-*)
  (( ${#old[@]} )) && rm -rf -- "${old[@]}"
  return 0
}

state="$("$systemctl_bin" --user is-active "$unit" 2>/dev/null)"
peak="$(mib "$("$systemctl_bin" --user show -p MemoryPeak --value "$unit" 2>/dev/null)")"
paused=""
if [[ "$state" != inactive ]]; then
  # A slow first compile must not look like a hung server: the watchdog waits until the page answers.
  if "$systemctl_bin" --user is-active --quiet "$watchdog"; then
    "$systemctl_bin" --user stop "$watchdog" && paused=yes
    trap '[[ -n "$paused" ]] && "$systemctl_bin" --user start "$watchdog"' EXIT
  fi
  if ! "$systemctl_bin" --user stop "$unit"; then
    echo "acdev-dev-restart: could not stop $unit; cache left alone" >&2
    exit 1
  fi
fi

size=0
[[ -d "$cache" ]] && size="$(du -sm -- "$cache" 2>/dev/null | cut -f1)"
[[ "$size" =~ ^[0-9]+$ ]] || size=0
note="cache ${size}M within cap ${cap}M, kept"
if (( size > cap )); then
  if mv -T -- "$cache" "$cache.old-$now"; then
    note="cache ${size}M above cap ${cap}M, cleared"
  else
    note="cache ${size}M above cap ${cap}M, could not move it"
  fi
fi

if [[ "$state" == inactive ]]; then
  delete_old
  echo "acdev-dev-restart: $unit was stopped on purpose and stays stopped; $note"
  exit 0
fi

status=0
answer=""
if ! "$systemctl_bin" --user start "$unit"; then
  status=1
  answer="; start failed"
elif [[ -n "$url" ]]; then
  curl_args=(-s -o /dev/null -m 60 -w '%{http_code}')
  [[ -n "$host" ]] && curl_args+=(-H "Host: $host")
  began="$(date +%s)"
  code="000"
  for (( i = 0; i < tries; i++ )); do
    code="$("$curl_bin" "${curl_args[@]}" "$url" 2>/dev/null)"
    code="${code:-000}"
    case "$code" in
      5??|000) "$sleep_bin" 5 ;;
      *) break ;;
    esac
  done
  answer="; $url answered $code after $(( $(date +%s) - began ))s"
fi
if [[ -n "$paused" ]]; then
  "$systemctl_bin" --user start "$watchdog" && paused="" && answer="$answer; watchdog resumed"
fi

# The old cache goes only after the first compile, so the two never compete for the disk.
delete_old
memory="$(mib "$("$systemctl_bin" --user show -p MemoryCurrent --value "$unit" 2>/dev/null)")"
echo "acdev-dev-restart: $unit restarted (memory peak since its last start $peak); $note$answer; memory $memory"
exit "$status"
