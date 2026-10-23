#!/bin/sh
# AUT-2203: the sole privileged schema operation admitted by this step.
# Run on stdin inside the reviewed PostgreSQL container, after a verified
# snapshot and writer fencing. Never accept SQL, filenames or role arguments.
set +x
set -eu
[ "$#" = 0 ] || { printf 'Extension migration takes no arguments.\n' >&2; exit 1; }
[ "${POSTGRES_USER:-}" = ac_owner ] && [ "${POSTGRES_DB:-}" = ac_platform ] || {
  printf 'Unexpected extension migration database identity.\n' >&2
  exit 1
}
: "${POSTGRES_PASSWORD:?Owner password must be injected by the existing runtime}"
export PGPASSWORD="$POSTGRES_PASSWORD"
psql -X --no-password --quiet --single-transaction --set ON_ERROR_STOP=1 \
  --host 127.0.0.1 --username ac_owner --dbname ac_platform <<'SQL'
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
DO $guard$
BEGIN
  IF current_user <> 'ac_owner' OR current_database() <> 'ac_platform'
     OR NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
     OR current_setting('server_version_num') <> '180006'
     OR NOT ('pg_stat_statements' = ANY(string_to_array(
       replace(current_setting('shared_preload_libraries'), ' ', ''), ','))) THEN
    RAISE EXCEPTION 'Extension migration requires the pinned owner/database/preloaded PostgreSQL';
  END IF;
  IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('ac_migrator', 'ac_runtime', 'ac_backup')
      AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
      AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit) <> 3 THEN
    RAISE EXCEPTION 'Restricted database role contract changed';
  END IF;
END
$guard$;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public VERSION '1.12';
DO $verify$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_extension e
    JOIN pg_namespace n ON n.oid = e.extnamespace
    JOIN pg_roles r ON r.oid = e.extowner
    WHERE e.extname = 'pg_stat_statements' AND e.extversion = '1.12'
      AND n.nspname = 'public' AND r.rolname = 'ac_owner'
  ) THEN
    RAISE EXCEPTION 'Existing pg_stat_statements does not match reviewed version/schema/owner';
  END IF;
END
$verify$;
SQL
