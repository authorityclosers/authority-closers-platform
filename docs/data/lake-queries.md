# Learning lake, version 1

`ac-lake-export` exports the previous **UTC** day's `analytics_events` and
`lead_desk_events` at 01:15 UTC (plus up to 15 minutes jitter). It reads one
repeatable-read, read-only PostgreSQL snapshot. These are observations for
analysis, never progress, payment, access or official scoring facts. No call
content, model training, or external call processing is activated here.

Objects live in the private, encrypted Sydney bucket:

```
s3://ac-archive-283923228069-apse2/lake/<env>/<table>/dt=YYYY-MM-DD/part-<n>-<sha256>.parquet
s3://ac-archive-283923228069-apse2/lake/<env>/<table>/dt=YYYY-MM-DD/manifest.json
```

Environments are `dev`, `staging`, `production`. Each table has a checked-in
JSON contract under `packages/python/ac_platform/telemetry/lake_contracts/`:
exact columns, Arrow types, enums, numeric limits and maximum null rates. A bad
row refuses that day's export; it is never silently skipped. Empty days have a
typed zero-row Parquet part. Reading uses 10,000-row chunks, not a day in memory.

Analytics rows must have granted product-analytics consent and unexpired source
retention. Both tables also check current person/workspace privacy switches and
exclude sandboxes. Lead Desk exports only event kind, time and pseudonymous
identifiers: it never even selects `data`, notes, messages, contact details or
command bodies. Raw analytics payloads, generic code strings, error text,
endpoint labels, element labels and fingerprints are dropped. Selected payload
fields survive only as fixed enums or bounded numbers. `retention_expires_at`
travels with each analytics row; readers must exclude expired rows. The operator
must verify the lake's object-retention policy before enabling export, consistent
with the existing 180-day analytics notice; export is not permission to retain
source observations indefinitely. Lead metadata has no newly inferred business
retention rule in this change.

All tenant, person, session, lead and event identifiers use HMAC-SHA256 with
`AC_LAKE_HMAC_KEY_V1` from Infisical **prod `/ops`**, injected only in memory.
Messages are JSON arrays of version, environment, tenant, entity kind and id.
Thus person references join across the two tables within a workspace, and cannot
join across environments or tenants. Keep V1 stable for longitudinal analysis;
a later rotation must use a new version and migration plan. Never store the key
or credentials in SQL, shell history, logs or this repository.

Parts use content-addressed names. Every uploaded object's length, SHA-256 S3
checksum and AES256 encryption are read back before success. All parts of both
tables are uploaded before either table manifest. A manifest is each table's
commit marker and includes its row count, part checksums, sizes, schema fingerprint
and pseudonym version. A retry with identical inputs reuses the same keys. A new
snapshot can add or omit late events; it supersedes the manifest without deleting
objects. **Read the manifest's part list**, not a `part-*.parquet` glob: orphaned
parts from an interrupted or superseded export may remain. Table manifests commit
independently; consumers needing both must require both for the same day.

There is no backfill switch: a nightly run exports the previous day only. A missed
day or late arrival beyond the snapshot requires a reviewed backfill task. Source
rows and audit history are never changed by export.

## Browser capture

Capture is unsampled within the existing intake limits (2,000 events/person/day,
1,200 events/workspace/minute). Every same-origin `/v1/` fetch is timed through response headers or network
rejection, including fast and background requests. The original response/error
is preserved. XHR is timed through load-end (including failure/abort). Resource Timing
supplies earlier buffered requests without duplicating intercepted requests. Telemetry endpoints are excluded to avoid recursion. API
URLs use a fixed vocabulary with unknown segments replaced by `id`; queries,
fragments and bodies never leave. Timing bands are `<100`, `100–300`, `300–1000`,
`1000–3000`, `3000–10000`, `>=10000` ms. Existing slow-call metrics remain for
compatibility. API endpoint labels are not copied into the lake.

Clicks (touch-generated clicks included, once) carry only element role, screen and
one of 12 viewport grid cells. Scroll is coalesced at 250 ms and reports new depth
quarters per scroll pane per route. Existing screen events measure visible time,
excluding the dialler/background. FCP/LCP/INP/CLS/TTFB remain browser web vitals;
JS errors contain class and source fingerprint, never message or stack text.
Route timing ends after the committed route has two animation-frame opportunities;
it starts at a link click/Back, or at commit for programmatic navigation without
an observed input. First navigation starts at the navigation time origin.

Batches flush at 50 events, 10 seconds, or hide/page exit using `sendBeacon`
(with keepalive fetch fallback). No beacon starts a taxonomy fetch during exit.
The authoritative intake checks current consent on every batch. Privacy refresh
clears queued observations. The queue is bounded at 1,000 events and network
failures drop a batch: this is best-effort analytics, not an audit log or an
exactly-once interaction ledger. No listener reads typed input, names or numbers.

## DuckDB: read committed parts directly from S3

Use an approved **read-only** AWS identity with `GetObject`/prefix-list access,
provided by the normal credential chain. The archive writer is for the job only.
Do not put keys in SQL or print them. Run with DuckDB's `httpfs` extension available:

```sql
INSTALL httpfs;
LOAD httpfs;
CREATE SECRET lake_reader (
  TYPE s3, PROVIDER credential_chain, REGION 'ap-southeast-2',
  SCOPE 's3://ac-archive-283923228069-apse2/lake/dev/'
);

-- Read a chosen day's committed manifest; use a date range of manifests for trends.
SET VARIABLE analytics_parts = (
  SELECT list('s3://ac-archive-283923228069-apse2/' || part.key)
  FROM (
    SELECT unnest(parts) AS part
    FROM read_json_auto(
      's3://ac-archive-283923228069-apse2/lake/dev/analytics_events/dt=2026-10-28/manifest.json',
      hive_partitioning = false
    )
  )
);
CREATE OR REPLACE TEMP VIEW events AS
SELECT * FROM read_parquet(getvariable('analytics_parts'), hive_partitioning = true)
WHERE retention_expires_at > current_timestamp;

-- Daily active people per tenant (pseudonyms are workspace-scoped).
SELECT dt, tenant_ref, count(DISTINCT subject_ref) AS daily_actives
FROM events GROUP BY ALL ORDER BY dt, tenant_ref;

-- Ordered onboarding funnel within the same pseudonymous session.
WITH started AS (
  SELECT tenant_ref, subject_ref, session_ref, min(occurred_at) AS started_at
  FROM events WHERE event_name = 'sx.flow' AND flow = 'onboarding' AND outcome = 'start'
  GROUP BY ALL
), reached AS (
  SELECT s.*, min(e.occurred_at) FILTER (WHERE e.outcome = 'step') AS step_at,
         min(e.occurred_at) FILTER (WHERE e.outcome = 'done') AS done_at
  FROM started s LEFT JOIN events e
    ON e.tenant_ref = s.tenant_ref AND e.subject_ref = s.subject_ref
    AND e.session_ref = s.session_ref AND e.occurred_at >= s.started_at
    AND e.event_name = 'sx.flow' AND e.flow = 'onboarding'
  GROUP BY ALL
)
SELECT count(*) AS starts, count(step_at) AS reached_step,
       count(*) FILTER (WHERE done_at >= step_at) AS completed_after_step FROM reached;

-- Friction by screen and grid cell; suppress groups involving fewer than 3 people.
SELECT screen, zone, kind, count(*) AS taps, count(DISTINCT subject_ref) AS people
FROM events WHERE event_name = 'sx.tap_issue'
GROUP BY ALL HAVING count(DISTINCT subject_ref) >= 3 ORDER BY taps DESC;

-- Actual web-vital percentiles. CLS is stored multiplied by 1,000, not milliseconds.
SELECT screen, metric, quantile_cont(value, [0.5, 0.9, 0.95]) AS milliseconds
FROM events WHERE event_name = 'sx.web_vital' AND metric IN ('fcp', 'lcp', 'inp', 'ttfb')
GROUP BY ALL;

-- API percentile bands: lower bounds, not invented exact latency measurements.
SELECT screen, quantile_disc(CASE band
  WHEN 'lt100' THEN 0 WHEN '100_300' THEN 100 WHEN '300_1000' THEN 300
  WHEN '1000_3000' THEN 1000 WHEN '3000_10000' THEN 3000 WHEN 'ge10000' THEN 10000
END, [0.5, 0.9, 0.95]) AS percentile_band_lower_ms
FROM events WHERE event_name = 'sx.api_timing' AND background = 'no' GROUP BY ALL;
```

Read `lead_desk_events` by replacing the table in the manifest query and variable
name; join its `actor_ref` to analytics `subject_ref` within the same `tenant_ref`.
A shared actor reference is only an observation link, never canonical progress.

## Installation and activation (operator)

The repository ships disabled. No staging or production service is enabled by a
builder. After green checks, the operator installs the tested revision:

1. Build/install the wheel with the `lake` extra into
   `/opt/ac-lake-export/.venv` (Python 3.12); PyArrow is pinned in `uv.lock` and is
   optional in the application runtime. Install `ac-lake-export` root-owned at
   `/usr/local/sbin/`, and the service/timer into `/etc/systemd/system/`.
   The existing root-owned `/usr/local/sbin/ac-archive-put` and AWS CLI must exist.
2. In Infisical prod `/ops`, provision `AC_LAKE_HMAC_KEY_V1` as 32 random bytes
   represented by 64 hex characters using stdin, without printing it. Existing
   `AC_ARCHIVE_AWS_ACCESS_KEY_ID`, `AC_ARCHIVE_AWS_SECRET_ACCESS_KEY`,
   `AC_ARCHIVE_BUCKET`, `AC_ARCHIVE_REGION` are fetched at runtime. The runner
   pins the requested bucket and Sydney region and uses no inherited AWS profile
   or endpoint. Confirm the writer can PutObject/GetObject under `lake/`; no
   deletion or lifecycle permission is requested for the writer.
3. Create root-only `/etc/authority-closers/lake/dev.env` with:
   `AC_LAKE_EXPORT_ENABLED=1` and
   `AC_LAKE_DATABASE_URL_FILE=/etc/authority-closers/development/database-url-live`.
   This file contains flags and a file path, never copied credentials. Verify the
   database file is dev's. Review bucket retention before activation.
4. `systemctl daemon-reload`, then `systemctl start ac-lake-export@dev.service`.
   Require a successful verified manifest for each table and read the Parquet
   back. Then `systemctl enable --now ac-lake-export@dev.timer`.
5. Keep staging/production config absent (or `AC_LAKE_EXPORT_ENABLED=0`).
   **Production enablement belongs to the orchestrator after review.** Disabling
   the timer/flag stops future writes and does not delete archived objects.

The `-I` script uses fixed root-owned executables, a minimal child environment,
private temporary files and low CPU/I/O priority. Provider errors and source
exceptions are replaced with fixed diagnostics; credentials never enter argv.
