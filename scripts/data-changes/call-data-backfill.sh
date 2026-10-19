#!/usr/bin/env bash
# Call data engine backfill on staging or production: every stored call read once by
# the fast pipeline, then the deep pipeline, within the Admin daily caps.
#
# Owner approval (19 Oct 2026, relayed by the orchestrator): fast backfill (staging
# ~Rs 42, production ~Rs 2.5) and "yes deep" (deep backfill staging ~Rs 147,
# production ~Rs 9). Runbook: scripts/data-changes/CALL-DATA-BACKFILL.md
#
# Dry run by default (lists what would be read, spends nothing). With --apply it:
#   1. refuses while a release holds /run/ac-release.lock (never during a promote);
#   2. takes a verified database snapshot (ac-db-snapshot);
#   3. pauses the automatic runner (one runner per database): the systemd unit and
#      the runner it left inside the worker container (stopping `docker exec` does
#      not stop the process inside), runs the backfill, and always restarts the unit;
#   4. prints every outcome line count and the spend and object counts (content-free).
#
#   sudo scripts/data-changes/call-data-backfill.sh <staging|production> [--apply]
set -euo pipefail

env_name=${1:?usage: call-data-backfill.sh <staging|production> [--apply]}
mode=${2:-dry-run}
case "$env_name" in staging | production) ;; *) echo "staging or production only" >&2; exit 2 ;; esac
[[ $mode == dry-run || $mode == --apply ]] || { echo "second argument: --apply or nothing" >&2; exit 2; }

worker=ac-application-$env_name-sales-xray-worker-1
postgres=ac-application-$env_name-postgres-1
runner=(docker exec "$worker" python -m ac_platform.call_data.runner
  --service-config /run/ac-sales-xray/service.json
  --database-url-file /run/ac-sales-xray/database-url
  --not-before 2026-01-01T00:00:00+00:00 --recent-hours 8760 --limit 200 --backfill)

summary() {
  docker exec -i -e PGOPTIONS="-c default_transaction_read_only=on" "$postgres" sh -c \
    'PGPASSWORD=$POSTGRES_PASSWORD exec psql -U $POSTGRES_USER -d ac_platform -At -F " | "' <<'SQL'
SELECT 'runs', pipeline, state, count(*), round(coalesce(sum(cost_inr), 0), 2)
FROM call_data_runs WHERE trigger = 'backfill' GROUP BY 2, 3 ORDER BY 2, 3;
SELECT 'objects', pipeline, count(*) FILTER (WHERE NOT retracted),
       count(*) FILTER (WHERE retracted),
       count(*) FILTER (WHERE supersedes_id IS NOT NULL AND NOT retracted)
FROM call_objects WHERE erased_at IS NULL GROUP BY 2 ORDER BY 2;
SQL
}

# The automatic runner's process inside the worker (and its infisical parent): SIGTERM,
# then wait until none is left. Prints what it found; never touches a backfill run.
stop_container_runner() {
  docker exec -i "$worker" python - <<'PY'
import os
import signal
import time


def runners():
    found = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            parts = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        if b"ac_platform.call_data.runner" in parts and b"--loop" in parts:
            found.append(int(pid))
    return found


before = runners()
for pid in before:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
for _ in range(60):
    if not runners():
        break
    time.sleep(1)
left = runners()
print(f"automatic runner processes stopped: {len(before) - len(left)}, still running: {len(left)}")
raise SystemExit(1 if left else 0)
PY
}

if [[ $mode == dry-run ]]; then
  echo "dry run on $env_name: calls the fast pipeline would read (deep follows each fast read)"
  "${runner[@]}" --pipeline fast | tail -n +2
  exit 0
fi

exec 9>/run/ac-release.lock
flock -n 9 || { echo "a release is running; try again after it" >&2; exit 3; }
snapshot=$(/usr/local/sbin/ac-db-snapshot "$env_name" call-data-backfill | tail -1)
echo "snapshot: $snapshot"
systemctl stop "ac-call-data@$env_name" 2>/dev/null || true
trap 'systemctl start "ac-call-data@$env_name" 2>/dev/null || true' EXIT
stop_container_runner
lines=$(mktemp)
"${runner[@]}" --pipeline both --apply > "$lines" 2>&1 || echo "runner exit $?"
grep -o '"outcome": "[a-z_:]*"\|"skipped": "[a-z_]*"\|"stopped": "[a-z_]*"' "$lines" | sort | uniq -c || true
if grep -q '"another_runner"' "$lines"; then
  echo "another runner held the lock; nothing was read" >&2
  rm -f "$lines"
  exit 4
fi
rm -f "$lines"
summary
