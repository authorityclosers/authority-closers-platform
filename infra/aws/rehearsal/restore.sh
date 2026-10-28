#!/usr/bin/env bash
# Disposable AWS host only. No provider calls; direct PostgreSQL backup/restore.
# shellcheck disable=SC2016 # Credentials expand inside the containers only.
set -euo pipefail
umask 077
rehearsal_root="${HOME}/rehearsal"
[[ -f "$rehearsal_root/FICTIONAL-ONLY" ]] || exit 1
restore_root="$(mktemp -d "$rehearsal_root/restore-XXXXXXXX")"
restore_name="ac-rehearsal-restore-${restore_root##*-}"
primary=ac-rehearsal-postgres-1
cleanup() { docker rm -f "$restore_name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
python3 - "$restore_root" <<'PY'
import pathlib,secrets,sys
root=pathlib.Path(sys.argv[1])
values={'POSTGRES_DB':'ac_platform','POSTGRES_USER':'ac_owner',
        'POSTGRES_INITDB_ARGS':'--auth-host=scram-sha-256 --auth-local=scram-sha-256 --data-checksums',
        'PGDATA':'/var/lib/postgresql/data'}
for name in ('POSTGRES_PASSWORD','AC_DB_RUNTIME_PASSWORD','AC_DB_MIGRATOR_PASSWORD','AC_DB_BACKUP_PASSWORD'):
 values[name]=secrets.token_hex(32)
(root/'restore.env').write_text(''.join(f'{k}={v}\n' for k,v in values.items()))
PY
cat > "$restore_root/counts.sql" <<'SQL'
SELECT format('SELECT %L, count(*) FROM %I.%I;', tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
SQL
# Keep the primary dump and its exact row-count inventory stable by draining writers.
"$rehearsal_root/compose.sh" stop --timeout 30 api worker sales-xray-worker
start=$(date +%s%N)
docker exec -i "$primary" sh -euc 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U ac_owner -d ac_platform -At' \
  < "$restore_root/counts.sql" > "$restore_root/source-counts.txt"
docker exec "$primary" sh -euc 'PGPASSWORD="$AC_DB_BACKUP_PASSWORD" pg_dump -h 127.0.0.1 -U ac_backup -d ac_platform --format=custom' \
  > "$restore_root/fictional.dump"
dump_end=$(date +%s%N)
"$rehearsal_root/compose.sh" up -d --no-deps --wait --wait-timeout 120 api worker sales-xray-worker
sudo install -d -o 999 -g 999 -m 700 "$restore_root/data"
docker run -d --name "$restore_name" --network none --memory 384m --memory-swap 384m \
  --shm-size 128m --user 999:999 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --env-file "$restore_root/restore.env" \
  --mount "type=bind,source=$restore_root/data,target=/var/lib/postgresql/data" \
  --mount "type=bind,source=$rehearsal_root/application/postgres/init,target=/docker-entrypoint-initdb.d,readonly" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --tmpfs /var/run/postgresql:rw,noexec,nosuid,nodev,size=16m,uid=999,gid=999 \
  pgvector/pgvector:pg17 postgres -c shared_buffers=128MB -c effective_cache_size=1GB \
  -c work_mem=4MB -c maintenance_work_mem=64MB -c max_connections=60 >/dev/null
for _attempt in $(seq 1 60); do
  if docker exec "$restore_name" sh -euc 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U ac_owner -d ac_platform -Atqc "SELECT count(*)=3 FROM pg_roles WHERE rolname IN ('\''ac_runtime'\'','\''ac_migrator'\'','\''ac_backup'\'')"' | grep -qx t; then break; fi
  sleep 1
done
restore_start=$(date +%s%N)
docker exec -i "$restore_name" sh -euc 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h 127.0.0.1 -U ac_owner -d ac_platform --exit-on-error' \
  < "$restore_root/fictional.dump" > "$restore_root/restore.log" 2>&1
restore_end=$(date +%s%N)
docker exec -i "$restore_name" sh -euc 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U ac_owner -d ac_platform -At' \
  < "$restore_root/counts.sql" > "$restore_root/restored-counts.txt"
cmp "$restore_root/source-counts.txt" "$restore_root/restored-counts.txt"
docker inspect --format '{{.State.OOMKilled}} {{.RestartCount}}' "$restore_name" > "$restore_root/container-state.txt"
python3 - "$restore_root" "$start" "$dump_end" "$restore_start" "$restore_end" <<'PY'
import pathlib,sys,json
root=pathlib.Path(sys.argv[1]); start,dump_end,restore_start,restore_end=map(int,sys.argv[2:])
counts={line.split('|')[0]:int(line.split('|')[1]) for line in (root/'source-counts.txt').read_text().splitlines() if '|' in line}
value={'dump_seconds':(dump_end-start)/1e9,'restore_seconds':(restore_end-restore_start)/1e9,
       'dump_bytes':(root/'fictional.dump').stat().st_size,'all_table_counts_match':True,
       'tables':len(counts),'rows':counts,'restore_container_state':(root/'container-state.txt').read_text().strip()}
(root/'result.json').write_text(json.dumps(value,indent=2)); print(json.dumps(value))
PY
