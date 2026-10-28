#!/usr/bin/env bash
# Kill the exact host PID, so Docker treats it as a crash, not an intentional stop.
set -euo pipefail
[[ -f "${HOME}/rehearsal/FICTIONAL-ONLY" ]] || exit 1
case "${1:-}" in api|worker) service="$1" ;; *) echo 'api or worker required' >&2; exit 1 ;; esac
name="ac-rehearsal-${service}-1"
project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$name")
[[ "$project" == ac-rehearsal ]] || exit 1
pid=$(docker inspect --format '{{.State.Pid}}' "$name")
[[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 ]] || exit 1
echo "crash-$service $(date -u +%FT%TZ)"
sudo kill -KILL "$pid"
