# Telemetry capacity and recovery

Sales Xray accepts up to **20,000 events per person per rolling 24 hours**, with
503 `telemetry_backpressure` above that limit. Workspace admission remains 1,200
events/minute. Neither limit changes canonical product state.

## Capture budget

The capture code in `app/telemetry-auto.tsx` emits one `sx.tap` per click, an
optional `sx.feature_used`, and `sx.action_timing` for timed actions. Each API
request adds `sx.api_timing` (telemetry requests excluded); slow requests can
also emit `sx.api_slow`. Navigation adds screen and route timing observations.
Scroll is coalesced at 250 ms and emits only new depth quarters per pane/route,
not 240 events/minute continuously.

A heavy-use planning minute of six timed, named taps (18 events), six API
requests (6), one navigation (screen + route timing: 2), four scroll quarters
(4), plus two errors/vitals/other observations gives **32 events/minute**.
Eight active hours give 15,360; 20,000 allows 30% headroom (41.7/minute over eight
hours). This is a source-derived workload estimate, not a measured production
rate or a guarantee for arbitrary automation. Screen-hidden and slow requests
can add events; monitor backpressure before raising limits again.

## Retention and bounded backup

This repair uses the owner's backup-exclusion alternative. **All event kinds
retain their existing 180-day expiry** in Postgres and the learning lake; no
shorter per-kind purge window or Admin query window is introduced. Existing
expired-row purge and privacy controls remain unchanged. Nightly export can
still read yesterday's events, and lake recipes still filter the 180-day
`retention_expires_at` field. Lake object expiry is 178 days after upload.

The canonical `ac-postgres-backup.py` writer uses
`--exclude-table-data=public.analytics_events`: schema, indexes and constraints
remain in the dump, but disposable analytics rows do not. No other table data
is excluded. Metadata includes `excluded_table_data: {"analytics_events": N}`,
where N is the actual source snapshot count. The drill explicitly queries the
restored analytics table and requires it to be empty.
The existing canonical `row_counts` inventory remains unchanged.
Restore validation accepts historical full-data inventories and the explicit
new exclusion, rejects other exclusions, and requires analytics to restore
empty while preserving exact parity for the existing canonical inventory,
including audit records. Counts prove inventory parity, not row-content equality.

The fixed **64 MiB** dump refusal, backup storage projection, and restore-drill
size limit remain unchanged. Analytics row growth contributes **zero data
bytes** to these logical dumps; schema overhead remains. Other product growth
can still trigger the refusal. Full deployment snapshots and other backup
writers are unchanged and may still include analytics.

Install matching writer and restore helpers together through the operator's
normal release route before relying on this policy. Older strict metadata
readers refuse the new inventory; do not silently strip it. This work neither
installs helpers nor runs a backup, purge, restore or production data change.

## Capacity estimate and recovery limits

At the reported 9.8 MB / 12,278 rows, budget about **800 bytes/row** including
current table/index overhead. At 20,000 rows/day/person this is about **16 MB/day**
and **2.88 GB/person at 180 days**, before bloat and changing payload/index size.
For N fully active people multiply by N. This alternative protects logical
backup capacity, not Postgres disk growth: monitor table size and export
receipts; a future shorter cache requires a separately verified export/purge
handoff. Do not pretend a 14-day cache alone guarantees a 64 MiB dump.

A logical restore intentionally starts with empty analytics. The lake preserves
successfully exported historical observations for analysis; it is not an
automatic replay into Postgres. Since export runs nightly, unexported analytics
can be lost in a logical-only recovery. Audit-critical and canonical tables
retain their existing recovery contract. Verify both daily manifests and alert
on missed exports; missed days require the documented reviewed backfill route.
