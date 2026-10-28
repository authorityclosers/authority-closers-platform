#!/usr/bin/env bash
# Run on the throwaway host only, after scp of the documented infra inputs.
set -euo pipefail
root="${HOME}/rehearsal"
[[ -f "$root/FICTIONAL-ONLY" && -f "$root/runtime.env" && -f "$root/application/compose.rehearsal.yaml" ]] || exit 1
# Deliberately no sourcing an environment from ac, staging or production.
sudo chgrp 10001 "$root"
chmod 770 "$root"
chmod 755 "$root/application" "$root/application/postgres" "$root/application/postgres/init"
sudo chown -R 10001:10001 "$root/storage" "$root/scratch" "$root/media" "$root/spool" \
  "$root/native" "$root/scanner" "$root/identities"
sudo chown 10001:10001 "$root/database-url" "$root/pooled-database-url" "$root/challenge-secret"
chmod 644 "$root/approval.json" "$root/service.json" "$root/userlist.txt" \
  "$root/seed.py" "$root/FICTIONAL-ONLY" "$root/fixture-ids.json"
"$root/compose.sh" config --quiet
"$root/compose.sh" up -d --wait postgres
# shellcheck disable=SC2016 # Expand credentials only inside the rehearsal container.
"$root/compose.sh" exec -T postgres sh -euc \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U ac_owner -d ac_platform -At' <<'SQL' > "$root/userlist.txt"
SELECT '"' || rolname || '" "' || rolpassword || '"' FROM pg_authid WHERE rolname = 'ac_runtime';
SQL
"$root/compose.sh" up -d --wait pgbouncer
"$root/compose.sh" --profile release run --rm migrate > "$root/evidence/migrations.log" 2>&1
"$root/compose.sh" run --rm --no-deps -v "$root:/fixture" -e AC_REHEARSAL_ACK=fictional-aws-only \
  api python /fixture/seed.py > "$root/evidence/seed.log" 2>&1
"$root/compose.sh" up -d --wait --wait-timeout 150
