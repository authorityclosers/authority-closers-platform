-- AUT-2202: aggregate evidence only; execute with psql -XqAt -v ON_ERROR_STOP=1.
-- No rows, identities, SQL text, settings outside this allowlist, or resets.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '1s';
SELECT json_build_object(
  'kind', 'database', 'observed_at', clock_timestamp(),
  'postmaster_started_at', pg_postmaster_start_time(),
  'read_only', current_setting('transaction_read_only'),
  'version_num', current_setting('server_version_num'),
  'database_bytes', pg_database_size(current_database()),
  'connections', (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()),
  'stats_reset', (SELECT stats_reset FROM pg_stat_database WHERE datname = current_database())
);
SELECT json_build_object('kind', 'setting', 'name', name,
  'setting', setting, 'unit', unit, 'source', source, 'pending_restart', pending_restart)
FROM pg_settings
WHERE name IN ('shared_preload_libraries', 'shared_buffers', 'random_page_cost',
              'jit', 'work_mem', 'max_connections', 'compute_query_id')
ORDER BY name;
SELECT json_build_object('kind', 'table', 'relation', relname,
  'seq_scan', seq_scan, 'seq_tup_read', seq_tup_read, 'idx_scan', idx_scan,
  'idx_tup_fetch', idx_tup_fetch, 'estimated_live_rows', n_live_tup,
  'total_bytes', pg_total_relation_size(relid))
FROM pg_stat_user_tables
WHERE schemaname = 'public' AND relname IN ('conversation_runs',
  'conversation_report_drafts', 'conversation_brain4_reviews', 'conversation_processing_plans')
ORDER BY relname;
SELECT json_build_object('kind', 'index', 'relation', tablename,
  'index', indexname, 'definition', indexdef)
FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('conversation_runs',
  'conversation_report_drafts', 'conversation_brain4_reviews', 'conversation_processing_plans')
ORDER BY tablename, indexname LIMIT 100;
SELECT json_build_object('kind', 'extension', 'installed', EXISTS (
  SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'));
SELECT (EXISTS (SELECT 1 FROM pg_extension
  WHERE extname = 'pg_stat_statements' AND extnamespace = 'public'::regnamespace)
  AND 'pg_stat_statements' = ANY(string_to_array(
    replace(current_setting('shared_preload_libraries'), ' ', ''), ','))) AS statements_ready
\gset
\if :statements_ready
SELECT json_build_object('kind', 'statement_stats', 'stats_reset', stats_reset,
  'dealloc', dealloc) FROM public.pg_stat_statements_info;
-- Emit query IDs and fixed relation labels, never the representative SQL text.
SELECT json_build_object('kind', 'statement', 'queryid', s.queryid,
  'toplevel', s.toplevel, 'calls', s.calls,
  'total_exec_ms', s.total_exec_time, 'mean_exec_ms', s.mean_exec_time,
  'rows', s.rows, 'shared_blks_hit', s.shared_blks_hit,
  'shared_blks_read', s.shared_blks_read, 'temp_blks_written', s.temp_blks_written,
  'relations', ARRAY(SELECT label FROM (VALUES ('conversation_runs'),
    ('conversation_report_drafts'), ('conversation_brain4_reviews'),
    ('conversation_processing_plans')) AS labels(label)
    WHERE s.query ~ ('\m' || label || '\M') ORDER BY label))
FROM public.pg_stat_statements(true) AS s
WHERE s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY s.total_exec_time DESC, s.queryid LIMIT 20;
\else
SELECT json_build_object('kind', 'statement_stats', 'available', false,
  'reason', 'public_extension_and_preload_required');
\endif
ROLLBACK;
