-- Sales X-Ray usage metrics export (ac.sales-xray.usage-metrics/1).
--
-- One read-only statement that returns one JSON document of usage NUMBERS for
-- the environment it runs in. Run by ac-metrics-collect inside each
-- environment's own postgres container with default_transaction_read_only=on.
--
-- Never selected: call titles, transcripts, reports, prompts, audio, names,
-- emails, phone numbers, payloads. Rows carry opaque ids (call, company), dates,
-- stage/provider/model/version labels and counters. People appear only as
-- pseudonyms: 'p_' and 16 hex characters of HMAC-SHA-256(this environment's key,
-- the person id), from the pads in metrics_pseudonym_keys (usage_people.pseudonyms),
-- which never leave the database. No organisation or person name is exported:
-- each environment's Admin reads its own names live (orchestrator, 20 Oct 2026).
-- Prices are NOT computed here: the Admin API prices the counters from the repo
-- price sheet when the page is read.
--
-- Settings (PGOPTIONS -c ...): ac.metrics_environment, ac.metrics_days (default
-- 120), ac.metrics_fixtures (comma list of bundled canary fixture sha256).
WITH params AS (
  SELECT
    coalesce(nullif(current_setting('ac.metrics_environment', true), ''), 'unknown') AS environment,
    least(400, greatest(1, coalesce(nullif(current_setting('ac.metrics_days', true), ''), '120')::int)) AS days,
    array_remove(string_to_array(coalesce(current_setting('ac.metrics_fixtures', true), ''), ','), '') AS fixtures
),
win AS (
  SELECT now() - make_interval(days => p.days) AS since FROM params p
),
-- This environment's HMAC pads, read only where their table exists (through
-- query_to_xml, so an older schema still parses and exports no person).
pkey_xml AS (
  SELECT query_to_xml(
    'SELECT encode(inner_pad, ''hex'') AS i, encode(outer_pad, ''hex'') AS o'
    || ' FROM metrics_pseudonym_keys WHERE id = 1',
    false, false, '') AS x
  WHERE to_regclass('metrics_pseudonym_keys') IS NOT NULL
),
pkey AS (
  SELECT decode((xpath('/table/row/i/text()', x))[1]::text, 'hex') AS inner_pad,
         decode((xpath('/table/row/o/text()', x))[1]::text, 'hex') AS outer_pad
  FROM pkey_xml
),
fixture AS (
  SELECT DISTINCT fixture_sha256 AS sha FROM conversation_canary_submissions
  UNION
  SELECT unnest(p.fixtures) FROM params p
),
canary_call AS (
  SELECT DISTINCT g.recording_id
  FROM conversation_guest_submissions g
  JOIN conversation_canary_submissions c
    ON c.submission_id = g.submission_id AND c.tenant_id = g.tenant_id
  WHERE g.recording_id IS NOT NULL
),
-- Provider steps (C2 transcription, C4 facts, C5 report) with their job.
step_raw AS (
  SELECT
    t.recording_id AS call_id,
    t.tenant_id AS company_id,
    t.stage,
    j.status,
    j.attempt_count AS attempts,
    coalesce(j.provider_receipt ->> 'provider', q.quote ->> 'provider_id') AS provider,
    coalesce(j.provider_receipt ->> 'model', q.quote ->> 'provider_model') AS model,
    j.provider_receipt ->> 'validation_state' AS receipt_state,
    CASE WHEN json_typeof(j.provider_receipt -> 'usage') = 'object' THEN j.provider_receipt -> 'usage' END AS usage_json,
    CASE WHEN t.intent ->> 'duration_ms' ~ '^[0-9]{1,10}$' THEN (t.intent ->> 'duration_ms')::bigint END AS audio_ms,
    CASE WHEN j.dispatch_started_at IS NOT NULL AND j.receipt_recorded_at >= j.dispatch_started_at
         THEN round(extract(epoch FROM j.receipt_recorded_at - j.dispatch_started_at) * 1000)::bigint END AS provider_ms,
    coalesce(j.created_at, t.created_at) AS at
  FROM conversation_inference_tasks t
  LEFT JOIN jobs j ON j.id = t.job_id
  LEFT JOIN conversation_quotes q ON q.id = t.quote_id
  WHERE coalesce(j.created_at, t.created_at) >= (SELECT since FROM win)
),
step AS (
  SELECT s.*,
    (SELECT json_object_agg(e.key, (e.value::text)::bigint)
       FROM json_each(s.usage_json) e
      WHERE json_typeof(e.value) = 'number'
        AND e.value::text ~ '^[0-9]{1,12}$'
        AND e.key IN ('promptTokenCount', 'candidatesTokenCount', 'thoughtsTokenCount',
                      'totalTokenCount', 'cachedContentTokenCount',
                      'input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens',
                      'total_tokens', 'cached_tokens', 'cache_write_tokens', 'reasoning_tokens')
    ) AS usage
  FROM step_raw s
),
-- Local audio check (C0/C1): no provider cost, only time and outcome.
local_step AS (
  SELECT r.recording_id AS call_id, r.tenant_id AS company_id, j.status, j.attempt_count AS attempts,
    CASE WHEN r.completed_at >= r.created_at
         THEN round(extract(epoch FROM r.completed_at - r.created_at) * 1000)::bigint END AS run_ms,
    j.created_at AS at
  FROM conversation_runs r
  JOIN jobs j ON j.id = r.job_id
  WHERE j.kind = 'conversation.inspect_local.v1' AND j.created_at >= (SELECT since FROM win)
),
pointer AS (
  SELECT recording_id AS call_id, tenant_id AS company_id, model_id AS model, version,
         input_tokens, output_tokens, created_by, created_at AS at
  FROM conversation_pointer_reviews
  WHERE created_at >= (SELECT since FROM win)
),
-- Paid AI beyond call analysis, from each feature's own rows (owner, 20 Oct 2026: Admin
-- must show all AI spend): the call data engine (a start with no outcome counts Rs 2, as
-- the engine counts it), AI replies and partner quote facts. Counters and labels only.
ai_work AS (
  SELECT CASE WHEN d.pipeline = 'deep' THEN 'CDD' ELSE 'CDF' END AS stage,
         d.recording_id AS call_id, d.tenant_id AS company_id, d.person_id,
         coalesce(d.provider, 'gemini') AS provider, d.model_id AS model,
         d.state AS status, d.trigger AS work_trigger,
         coalesce(d.input_tokens, 0) AS input_tokens, coalesce(d.output_tokens, 0) AS output_tokens,
         CASE WHEN d.state = 'running' THEN 2 ELSE d.cost_inr END AS cost_inr,
         d.created_at AS at
  FROM call_data_runs d
  WHERE d.created_at >= (SELECT since FROM win)
    AND (d.state <> 'running'
         OR NOT EXISTS (SELECT 1 FROM call_data_runs o WHERE o.supersedes_id = d.id))
  UNION ALL
  SELECT 'AR', NULL, a.tenant_id, a.requested_by_person_id,
         coalesce(a.provider, 'gemini'), a.model, a.outcome, a.mode,
         coalesce(a.input_tokens, 0), coalesce(a.output_tokens, 0), a.cost_inr, a.created_at
  FROM lead_desk_ai_replies a
  WHERE a.created_at >= (SELECT since FROM win) AND a.input_tokens IS NOT NULL
  UNION ALL
  SELECT 'QF', f.recording_id, f.tenant_id, NULL::uuid, 'gemini', f.model_id, f.status, 'auto',
         coalesce(f.input_tokens, 0), coalesce(f.output_tokens, 0), NULL, f.created_at
  FROM partner_quote_facts f
  WHERE f.created_at >= (SELECT since FROM win) AND f.input_tokens IS NOT NULL
),
plan_latest AS (
  SELECT DISTINCT ON (recording_id) recording_id, id, state, manifest, created_at
  FROM conversation_processing_plans
  ORDER BY recording_id, created_at DESC
),
c1 AS (
  SELECT recording_id, max((payload ->> 'media_duration_ms')::bigint) AS ms
  FROM conversation_checkpoints
  WHERE stage = 'C1' AND json_typeof(payload) = 'object'
    AND payload ->> 'media_duration_ms' ~ '^[0-9]{1,10}$'
  GROUP BY recording_id
),
minutes AS (
  SELECT p.recording_id,
         sum(e.seconds) FILTER (WHERE e.kind = 'delivered') AS billed_s,
         min(e.created_at) FILTER (WHERE e.kind = 'delivered') AS delivered_at
  FROM conversation_report_minute_events e
  JOIN conversation_processing_plans p ON p.id = e.plan_id
  GROUP BY p.recording_id
),
gold AS (
  SELECT g.recording_id,
         count(*) FILTER (WHERE g.payload ->> 'verdict' = 'agree') AS agree,
         count(*) FILTER (WHERE g.payload ->> 'verdict' = 'partly') AS partly,
         count(*) FILTER (WHERE g.payload ->> 'verdict' = 'disagree') AS disagree
  FROM conversation_gold_rows g
  WHERE g.erased_at IS NULL
    AND NOT EXISTS (SELECT 1 FROM conversation_gold_rows n WHERE n.supersedes_id = g.id)
  GROUP BY g.recording_id
),
call_ids AS (
  SELECT call_id FROM step UNION SELECT call_id FROM local_step UNION SELECT call_id FROM pointer
  UNION
  SELECT id FROM conversation_recordings
  WHERE created_at >= (SELECT since FROM win) AND split_part(request_key, ':', 1) <> 'syn'
),
call AS (
  SELECT
    r.id AS call_id,
    r.tenant_id AS company_id,
    r.person_id,
    r.created_at AS at,
    r.state AS recording_state,
    CASE WHEN split_part(r.request_key, ':', 1) = 'syn' THEN 'synthetic'
         WHEN r.id IN (SELECT recording_id FROM canary_call) THEN 'canary'
         WHEN r.source_sha256 IN (SELECT sha FROM fixture) THEN 'qa'
         ELSE 'real' END AS kind,
    gs.capture_source,
    coalesce(
      CASE WHEN pl.manifest ->> 'duration_ms' ~ '^[0-9]{1,10}$' THEN (pl.manifest ->> 'duration_ms')::bigint END,
      c1.ms,
      u.reserved_seconds::bigint * 1000
    ) AS audio_ms,
    pl.state AS plan_state,
    pl.created_at AS accepted_at,
    m.delivered_at,
    coalesce(m.billed_s, 0) AS billed_s,
    pl.manifest ->> 'coaching_prompt_revision' AS prompt_revision,
    pl.manifest ->> 'fact_prompt_revision' AS fact_revision,
    pl.manifest ->> 'analysis_settings_revision' AS settings_revision,
    pl.manifest ->> 'output_profile' AS output_profile,
    pl.manifest ->> 'report_language' AS language,
    (SELECT s ->> 'model_id' FROM json_array_elements(CASE WHEN json_typeof(pl.manifest -> 'stages') = 'array' THEN pl.manifest -> 'stages' ELSE '[]'::json END) s WHERE s ->> 'stage' = 'C5' LIMIT 1) AS report_model,
    (SELECT s ->> 'model_id' FROM json_array_elements(CASE WHEN json_typeof(pl.manifest -> 'stages') = 'array' THEN pl.manifest -> 'stages' ELSE '[]'::json END) s WHERE s ->> 'stage' = 'C2' LIMIT 1) AS transcription_model,
    coalesce(gd.agree, 0) AS gold_agree,
    coalesce(gd.partly, 0) AS gold_partly,
    coalesce(gd.disagree, 0) AS gold_disagree
  FROM call_ids ci
  JOIN conversation_recordings r ON r.id = ci.call_id
  LEFT JOIN LATERAL (
    SELECT g.capture_source, g.usage_id FROM conversation_guest_submissions g
    WHERE g.recording_id = r.id ORDER BY g.created_at DESC LIMIT 1
  ) gs ON true
  LEFT JOIN conversation_acquisition_usage u ON u.id = gs.usage_id
  LEFT JOIN plan_latest pl ON pl.recording_id = r.id
  LEFT JOIN c1 ON c1.recording_id = r.id
  LEFT JOIN minutes m ON m.recording_id = r.id
  LEFT JOIN gold gd ON gd.recording_id = r.id
),
synthetic AS (
  SELECT (created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS n
  FROM conversation_recordings
  WHERE split_part(request_key, ':', 1) = 'syn' AND created_at >= (SELECT since FROM win)
  GROUP BY 1
),
hold_raw AS (
  SELECT b.scope_id, r.value AS v,
         to_timestamp((r.value -> 'quote' ->> 'created_at_epoch')::bigint) AS at
  FROM conversation_budget_accounts b, json_array_elements(b.snapshot -> 'reservations') r
  WHERE r.value -> 'quote' ->> 'created_at_epoch' ~ '^[0-9]{1,12}$'
),
hold AS (
  SELECT
    (h.at AT TIME ZONE 'UTC')::date AS day,
    h.scope_id,
    h.v ->> 'state' AS state,
    split_part(coalesce(h.v -> 'settlement' ->> 'receipt_ref', h.v ->> 'uncertainty_ref', h.v ->> 'release_reason_ref', ''), ':', 1) AS ref,
    h.v -> 'quote' ->> 'provider_id' AS provider,
    CASE WHEN (h.v -> 'quote' -> 'source' ->> 'recording_id') IN (SELECT recording_id::text FROM canary_call) THEN 'canary'
         WHEN (h.v -> 'quote' -> 'source' ->> 'source_sha256') IN (SELECT sha FROM fixture) THEN 'qa'
         ELSE 'real' END AS kind,
    count(*) AS n,
    sum(CASE WHEN h.v -> 'quote' ->> 'max_cost_paise' ~ '^[0-9]{1,12}$' THEN (h.v -> 'quote' ->> 'max_cost_paise')::bigint ELSE 0 END) AS held_paise,
    sum(CASE WHEN h.v -> 'settlement' ->> 'actual_paise' ~ '^[0-9]{1,12}$' THEN (h.v -> 'settlement' ->> 'actual_paise')::bigint ELSE 0 END) AS settled_paise
  FROM hold_raw h
  GROUP BY 1, 2, 3, 4, 5, 6
),
budget_setting AS (
  -- The Admin budget settings (owner, 19 Oct 2026): the newest audited revision per
  -- budget scope. Read from audit events, so the export also runs before migration 0099.
  SELECT DISTINCT ON (resource_id) resource_id AS scope_id,
         CASE WHEN payload -> 'after' ->> 'ceiling_paise' ~ '^[0-9]{1,12}$' THEN (payload -> 'after' ->> 'ceiling_paise')::bigint END AS ceiling_paise,
         payload -> 'after' ->> 'period' AS period,
         CASE WHEN payload -> 'after' ->> 'cap_paise' ~ '^[0-9]{1,12}$' THEN (payload -> 'after' ->> 'cap_paise')::bigint END AS cap_paise
  FROM audit_events
  WHERE action = 'conversation.budget_settings_changed'
  ORDER BY resource_id, occurred_at DESC
),
budget AS (
  SELECT b.scope_id, coalesce(s.period, 'lifetime') AS period, s.ceiling_paise,
         -- Monthly and daily: the cap per period. Lifetime: the ledger's cap, at most the ceiling.
         CASE WHEN s.period IN ('monthly', 'daily') THEN s.cap_paise
              WHEN b.snapshot ->> 'cap_paise' ~ '^[0-9]{1,12}$'
                THEN least((b.snapshot ->> 'cap_paise')::bigint, coalesce(s.ceiling_paise, (b.snapshot ->> 'cap_paise')::bigint)) END AS cap_paise,
         -- What the ledger counts against the cap: settled at its real cost, open at its quote.
         -- In a period, settled spend counts only when it was reserved inside the period
         -- (India time); money still held counts until it settles.
         (SELECT coalesce(sum(CASE
                   WHEN r ->> 'state' = 'released' THEN 0
                   WHEN r ->> 'state' = 'settled' AND s.period IN ('monthly', 'daily')
                     AND coalesce(CASE WHEN r -> 'quote' ->> 'created_at_epoch' ~ '^[0-9]{1,12}$'
                                       THEN (r -> 'quote' ->> 'created_at_epoch')::bigint END, 0)
                         < extract(epoch FROM date_trunc(CASE s.period WHEN 'daily' THEN 'day' ELSE 'month' END, now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata')
                     THEN 0
                   WHEN r ->> 'state' = 'settled' AND r -> 'settlement' ->> 'actual_paise' ~ '^[0-9]{1,12}$'
                     THEN (r -> 'settlement' ->> 'actual_paise')::bigint
                   WHEN r -> 'quote' ->> 'max_cost_paise' ~ '^[0-9]{1,12}$'
                     THEN (r -> 'quote' ->> 'max_cost_paise')::bigint
                   ELSE 0 END), 0)
            FROM json_array_elements(b.snapshot -> 'reservations') r) AS committed_paise
  FROM conversation_budget_accounts b
  LEFT JOIN budget_setting s ON s.scope_id = b.scope_id::text
),
waiting AS (
  -- Calls waiting for AI budget; they continue by themselves once it allows.
  SELECT count(*) AS n FROM conversation_processing_plans
  WHERE state = 'active' AND progress ->> 'failure_code' = 'budget_cap_reached'
),
budget_change AS (
  -- Each Admin budget settings revision: amounts and periods only, never the reason text.
  SELECT id, occurred_at AS at,
         CASE WHEN payload -> 'before' ->> 'ceiling_paise' ~ '^[0-9]{1,12}$' THEN (payload -> 'before' ->> 'ceiling_paise')::bigint END AS before_ceiling_paise,
         CASE WHEN payload -> 'after' ->> 'ceiling_paise' ~ '^[0-9]{1,12}$' THEN (payload -> 'after' ->> 'ceiling_paise')::bigint END AS ceiling_paise,
         payload -> 'before' ->> 'period' AS before_period,
         payload -> 'after' ->> 'period' AS period,
         CASE WHEN payload -> 'after' ->> 'cap_paise' ~ '^[0-9]{1,12}$' THEN (payload -> 'after' ->> 'cap_paise')::bigint END AS cap_paise
  FROM audit_events
  WHERE action = 'conversation.budget_settings_changed' AND occurred_at >= (SELECT since FROM win)
),
payment AS (
  SELECT a.tenant_id AS company_id, (e.verified_at AT TIME ZONE 'UTC')::date AS day, e.kind,
         coalesce(o.mode, s.mode) AS mode, e.currency, count(*) AS n, sum(coalesce(e.amount_minor, 0)) AS amount_minor
  FROM billing_payment_events e
  LEFT JOIN billing_orders o ON o.id = e.order_id
  LEFT JOIN billing_subscriptions s ON s.id = e.subscription_id
  LEFT JOIN billing_accounts a ON a.id = coalesce(o.account_id, s.account_id)
  WHERE e.kind IN ('payment.captured', 'subscription.charged', 'refund.processed')
    AND e.verified_at IS NOT NULL
  GROUP BY 1, 2, 3, 4, 5
),
subscription AS (
  SELECT a.tenant_id AS company_id, s.plan_key, s.plan_name, s.interval, s.seats, s.included_minutes,
         s.amount_minor, s.currency, s.mode, s.created_at
  FROM billing_subscriptions s JOIN billing_accounts a ON a.id = s.account_id
),
company AS (
  SELECT t.id AS company_id, t.slug,
    CASE WHEN starts_with(t.slug, 'ac-sandbox-') THEN 'sandbox'
         WHEN t.slug = 'authority-closers-public-learners' THEN 'personal'
         WHEN starts_with(t.slug, 'authority-closers') THEN 'internal'
         WHEN o.tenant_id IS NOT NULL THEN 'organisation'
         ELSE 'other' END AS kind
  FROM tenants t LEFT JOIN organisations o ON o.tenant_id = t.id
)
SELECT json_build_object(
  'schema', 'ac.sales-xray.usage-metrics/1',
  'environment', (SELECT environment FROM params),
  'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
  'window_days', (SELECT days FROM params),
  'migration', (SELECT max(version_num) FROM alembic_version),
  'companies', coalesce((SELECT json_agg(json_build_object('id', company_id, 'kind', kind) ORDER BY company_id) FROM company), '[]'::json),
  'calls', coalesce((SELECT json_agg(json_build_object(
      'id', call_id, 'company', company_id, 'person', 'p_' || left(encode(sha256((SELECT outer_pad FROM pkey) || sha256((SELECT inner_pad FROM pkey) || convert_to(person_id::text, 'UTF8'))), 'hex'), 16),
      'at', at, 'kind', kind, 'state', recording_state,
      'source', capture_source, 'audio_ms', audio_ms, 'plan', plan_state,
      'accepted_at', accepted_at, 'delivered_at', delivered_at, 'billed_s', billed_s,
      'prompt', prompt_revision, 'facts', fact_revision, 'settings', settings_revision,
      'profile', output_profile, 'language', language,
      'report_model', report_model, 'transcription_model', transcription_model,
      'gold', json_build_object('agree', gold_agree, 'partly', gold_partly, 'disagree', gold_disagree)
    ) ORDER BY at) FROM call), '[]'::json),
  'steps', coalesce((SELECT json_agg(json_build_object(
      'call', call_id, 'company', company_id, 'stage', stage, 'status', status, 'attempts', attempts,
      'provider', provider, 'model', model, 'receipt', receipt_state, 'usage', usage,
      'audio_ms', audio_ms, 'provider_ms', provider_ms, 'at', at
    ) ORDER BY at) FROM step), '[]'::json),
  'local_steps', coalesce((SELECT json_agg(json_build_object(
      'call', call_id, 'company', company_id, 'status', status, 'attempts', attempts, 'run_ms', run_ms, 'at', at
    ) ORDER BY at) FROM local_step), '[]'::json),
  'pointer_reviews', coalesce((SELECT json_agg(json_build_object(
      'call', call_id, 'company', company_id, 'model', model, 'version', version,
      'input_tokens', input_tokens, 'output_tokens', output_tokens, 'by', created_by, 'at', at
    ) ORDER BY at) FROM pointer), '[]'::json),
  'ai_work', coalesce((SELECT json_agg(json_build_object(
      'stage', stage, 'call', call_id, 'company', company_id,
      'person', 'p_' || left(encode(sha256((SELECT outer_pad FROM pkey) || sha256((SELECT inner_pad FROM pkey) || convert_to(person_id::text, 'UTF8'))), 'hex'), 16), 'provider', provider,
      'model', model, 'status', status, 'trigger', work_trigger,
      'input_tokens', input_tokens, 'output_tokens', output_tokens, 'cost_inr', cost_inr, 'at', at
    ) ORDER BY at) FROM ai_work), '[]'::json),
  'synthetic_calls', coalesce((SELECT json_agg(json_build_object('day', day, 'n', n) ORDER BY day) FROM synthetic), '[]'::json),
  'holds', coalesce((SELECT json_agg(json_build_object(
      'day', day, 'scope', scope_id, 'state', state, 'ref', ref, 'provider', provider, 'kind', kind,
      'n', n, 'held_paise', held_paise, 'settled_paise', settled_paise
    ) ORDER BY day) FROM hold), '[]'::json),
  'budgets', coalesce((SELECT json_agg(json_build_object(
      'scope', scope_id, 'cap_paise', cap_paise, 'committed_paise', committed_paise,
      'period', period, 'ceiling_paise', ceiling_paise
    )) FROM budget), '[]'::json),
  'waiting_calls', (SELECT n FROM waiting),
  'budget_changes', coalesce((SELECT json_agg(json_build_object(
      'id', id, 'at', at, 'before_ceiling_paise', before_ceiling_paise, 'ceiling_paise', ceiling_paise,
      'before_period', before_period, 'period', period, 'cap_paise', cap_paise
    ) ORDER BY at) FROM budget_change), '[]'::json),
  'payments', coalesce((SELECT json_agg(json_build_object(
      'company', company_id, 'day', day, 'kind', kind, 'mode', mode, 'currency', currency,
      'n', n, 'amount_minor', amount_minor
    ) ORDER BY day) FROM payment), '[]'::json),
  'subscriptions', coalesce((SELECT json_agg(json_build_object(
      'company', company_id, 'plan', plan_name, 'plan_key', plan_key, 'interval', interval, 'seats', seats,
      'included_minutes', included_minutes, 'amount_minor', amount_minor, 'currency', currency,
      'mode', mode, 'at', created_at
    ) ORDER BY created_at) FROM subscription), '[]'::json)
);
