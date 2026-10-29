# Weekly improvement engine

`infra/application/scripts/ac-improve` turns reviewed lake exports and numeric
operational aggregates into an owner report, engineering report, ranked task
outbox and longitudinal JSON/Markdown scoreboard. It observes product behavior;
it never changes access, payments, progress or scores of people. Prune means a
candidate experiment, never automatic removal or deletion.

## Run and inputs

Run in the capped agent slice. DuckDB is a CLI-job dependency, not an application
runtime dependency; this change does not modify manifests or lockfiles. The
first run used `uv run --with duckdb==2.0.0` (use the validated installed version
recorded with the run). No credentials or provider connections are implemented
in this engine. The orchestrator reads production through committed lake parts
or logged costq and places exports in a private local directory. It uses the
approved Infisical runtime pattern, never credentials in command arguments.

Copy each committed manifest and exactly its listed Parquet files into:

```
<lake-dir>/<environment>/<table>/dt=YYYY-MM-DD/{manifest.json,part-....parquet}
```

Both `analytics_events` and `lead_desk_events` are required for complete coverage.
Manifest environment/table/day/schema, SHA-256 and total row count are verified.
Orphan Parquet files are ignored. Lead Desk metadata contributes coverage only;
its content is never selected into the report. Missing manifests are unknown,
including previous-week deltas; committed zero-row manifests mean observed zero.
Expired analytics rows are excluded at query time. UTC windows are half open.
Default window is the seven full UTC days before today; baseline is the same
window seven days earlier. The inaugural 28–29 October window is partial, not a
full week, and includes 29 October only once its nightly manifest exists.

```bash
uv run --with duckdb python infra/application/scripts/ac-improve \
  --lake-dir /var/lib/ac-improve/lake --env production \
  --start 2026-10-28 --end-exclusive 2026-10-30 \
  --output /var/lib/ac-improve/reports --seed-api-freeze --ideas
```

Repeat with `--env dev`. The seeded freeze is explicitly owner-supplied evidence:
about 5,000 ms blocked and 25 endpoints affected, not a measured lake percentile.
Do not seed it every week. The engine refuses above 250,000 analytics rows per
window rather than silently sampling. DuckDB uses one thread and 256 MB;
operator must review capacity before increasing the bound. Concurrent writers
to the same output directory are unsupported; systemd serializes the two runs.

## What can be measured

- Exact p50/p95/p99 for action timings; completed flow journeys paired in order
  within tenant/person/session/flow. Cancels/abandons clear the pending start.
- Navigation and API timings in lake v1 are **bands**. Reports use discrete
  percentile **lower bounds** in ms; they never interpolate an exact latency.
  Endpoint labels and release labels are absent in the lake. Screen/action
  timing, journey and abandon-point groups require three distinct people;
  references never leave the process.
- API errors per 1,000 observed API timing events (4xx, 5xx, network); JS errors
  per 1,000 screen views. These are best-effort observations, not server totals.
  Upload interruptions count as failures; seller cancellations do not. There is
  no inference that an upload with no terminal event failed.
- Rage/dead tap counts, explicit flow abandon counts and cohort-suppressed
  abandon steps. Lack of a completion event is not proof of abandonment.
- Exact per-route API percentiles, event-loop stalls, CPU, unit costs, release
  comparisons, bug totals and CI timings need reviewed operational aggregates.
  Feature labels are stripped from lake v1 `feature_used`: zero use cannot be
  inferred from an absent label. A reviewed exposure/usage inventory is required.

Use `--aggregates current.json --previous-aggregates previous.json` with numeric
aggregate-only exports from the orchestrator. Each file has `start` and
`end_exclusive` matching its report window. Supported fields:

```json
{
  "start": "2026-10-28", "end_exclusive": "2026-10-30",
  "requests": 1000, "errors": 2, "cpu_ms": 12000,
  "spend_inr": 300, "analysed_minutes": 100, "active_sellers": 10,
  "event_loop_stalls": 1, "event_loop_stall_p95_ms": 5000,
  "bug_count": 4, "ci_p95_ms": 30000,
  "api_routes": [{"route": "/v1/calls/{id}", "latency_ms": [100, 200, 300]}],
  "features": [{"screen": "coaching", "exposures": 100, "uses": 0}],
  "release_comparisons": [{"release": "v1.6.0", "metric": "api_pxx_ms", "before": 100, "after": 150}]
}
```

The example is fictional. Do not treat its figures as production evidence.
API routes must be reviewed static templates, never real URLs, queries, names
or IDs. Latency arrays contain numbers only; maximum 250,000 per route.
Release comparisons must represent the deployed release versus its predecessor,
with equivalent coverage, and **lower-is-better** metrics. Feature inventory uses
contract screen labels; 100 exposures with zero uses creates a prune candidate.
Spend must be INR from costq, scoped consistently with analysed minutes and active
sellers. Do not invent an exchange rate, canonical seller definition or CPU cost.
Omit unavailable fields. Zero denominators and missing numerators remain unknown.
Visual CI artefacts are retained by wb-ci, not sent to the ideas model; this
version imports CI elapsed-time and bug-count aggregates, not raw reports/images.

## Ranking, ideas and HQ

Findings rank by `impact × confidence ÷ effort`. Initial values are transparent
heuristics (latency severity or incident counts, confidence 0–1, relative effort),
not a calibrated financial forecast. Speed threshold is 1,000 ms p95; release
regression threshold is +20%; unit-cost increase threshold is +20%; loop-delay
threshold is 100 ms. Counts require engineering interpretation at equal exposure.
All expected gains are experimental targets, not promises.

`--ideas` checks for ChatGPT subscription authentication and calls Codex in an
empty temporary working directory, read-only, shell tool disabled, with no user
configuration, no API key environment and a fixed Sol 6.1 model. Only aggregate
findings enter stdin. Structured JSON links each experiment to an existing
finding and tags it prune/speed/cost/quality with an expected gain. No files from
the lake or repository are passed. A timeout or usage limit stops the step; no
API-credit fallback. Empty findings skip the model. Auth and execution use the
installed `/home/acdev/.local/bin/codex`. See the official
[non-interactive Codex documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

`--sync-hq` finds exactly one MP16 parent by `orch:meet-20261028:mp16`, ensures
one task per `orch:improve:<environment>:<key>` (ideas have a separate stable
`idea:` key), then saves its `parentId` and current evidence, including existing
tasks. IDs and parent IDs are retained in `hq-state.json`. Findings use normal
priority initially. This is explicit task-writing authorization from the owner;
no messages or unrelated task changes are sent.

A speed task closes only when an exact p95 falls from above 1,000 ms to at most
1,000 ms, improves by at least 20%, and both windows contain at least 20 samples.
Band movements, missing data, seed anecdotes and disappearing observations never
close tasks. Closure notes include before/after ms and sample counts. Other
categories need a reviewed experiment verdict; this version does not auto-close
them. No task disappearance is interpreted as improvement.

If HQ access is unavailable, the outbox survives, including ideas and closures.
The root orchestrator can apply it without re-reading production or re-running
Codex, using the reviewed script:

```bash
python3 infra/application/scripts/ac-improve \
  --sync-outbox /var/lib/ac-improve/reports/production-2026-10-28-2026-10-30-hq-outbox.json \
  --output /var/lib/ac-improve/reports
```

Do not grant this builder broad sudo. Review stdout/exit status; failed HQ
operations leave the outbox and already saved IDs for an idempotent retry.

## Scheduling and verification

The service and weekly Monday 04:00 UTC timer are **shipped uninstalled and
disabled**. No enablement command was run. The service also requires the absent
`/etc/authority-closers/improve-enabled` marker. After review, the orchestrator
installs a tested DuckDB Python environment at `/opt/ac-improve/bin/python`,
provisions private input/output directories with read-only lake inputs, installs
the units and enables the timer. The template runs reporting for production
then dev, with 25% CPU and 512 MB memory. Its default does not invoke Codex or
root HQ; the orchestrator must wire the reviewed exports/aggregate paths and
subscription/HQ stages before enabling the full weekly pipeline. It must not
read application databases. Builders do not install or enable this service.

Scoreboard JSON preserves one entry per environment/window and Markdown shows
unit metrics. A rerun replaces that window's entry; owner/engineering JSON retains
all computed metrics and deltas. Reports are aggregate operational artefacts,
not an audit log; preserve run artefacts externally for revision history.

Focused checks: `uv run --with duckdb pytest -q tests/infra/test_ac_improve.py`,
Ruff on the script/tests, and the required `uv run python -c 'import ac_platform.http'`.
Tests use fictional data; they are not evidence of real production improvements.
