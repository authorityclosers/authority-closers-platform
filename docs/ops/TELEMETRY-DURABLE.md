# Durable product telemetry

Analytics are disposable observations. They never create canonical progress, access,
payment, audit or scoring state. This path uses the existing approved AC S3 archive,
not another data processor.

## Intake and recovery contract

After schema validation, session binding and the final current consent check, the API
writes the fixed `ac-telemetry-raw/1` envelope to an NDJSON journal and fsyncs the file
and directory. Only then does it evaluate hot-store admission, check the per-person
cap, resolve optional call references and write Postgres inside a savepoint.

- Normal intake: 202 with `spool_receipt`, stored/duplicate counts and event IDs.
- Hot-store cap: 202, `hot_store_full: true`, `reason: hot_store_full`; the accepted
  IDs identify the durable raw observations, including ones absent from Postgres.
- SQL/admission failure: 202, `reason: hot_store_unavailable`, receipt and IDs.
- Raw append/disk failure: 503. Consent/authentication/validation still fail closed.
  A database outage that prevents authentication or consent resolution cannot safely
  accept a new batch; browser retries are necessary in that case.

A final outer authentication-transaction commit failure can still make the HTTP
request fail after the journal append. The raw batch survives and retries preserve
IDs. The hot-store write is not claimed to be exactly once across both stores.

The envelope projects named ORM fields only, including consent/expiry provenance,
opaque workspace/person/session/event identifiers, route templates and taxonomy
allowlisted enum/numeric payloads. It includes no typed text, names, emails, headers,
IP addresses, raw call IDs or recording contents. Both HTTP and journal boundaries
validate the payload allowlist. The raw journal precedes optional keyed call-reference
enrichment in Postgres. Privacy opt-outs receive no raw record.

The browser retries network errors, 429 and 5xx using the same event IDs, with
10s exponential delays capped at 5 minutes and a maximum 1,000 queued events.
This queue lives in the page's memory: it cannot promise recovery after browser
termination. Beacon delivery on page exit also has no server acknowledgement.
Schema/auth refusals stop collection for that page. Consent taxonomy failures retry.

## Journal and S3 shipping

Production/staging reuse the API's existing durable `AC_INTAKE_SPOOL_ROOT` bind:
`$AC_INTAKE_SPOOL_ROOT/telemetry/<environment>` inside the API. On the host this is
`/srv/authority-closers/application/intake-spool/<environment>/telemetry/<environment>`.
Thus intake works before the optional dedicated mount overlay is activated.
Dev uses `/srv/authority-closers/sales-xray/development-live/telemetry/dev`, inside
the host API service's existing writable durable bind. `development` maps to `dev`. `AC_TELEMETRY_SPOOL_ROOT` overrides only the parent mount (tests use a
per-test temporary mount). There is no ephemeral-directory fallback.

Writers serialize with flock, append one batch per line and rotate closed UTC hours
from `.open` to `.ndjson`. File names carry UTC date/hour, safe hostname and a random
sequence. A segment also closes at 16 MiB to bound compression workspace. A failed partial append is truncated before returning an error. A trailing
fragment left by a killed writer is removed before the next append to that file;
newline-terminated acknowledged batches remain intact.

The default per-environment total allocation is 1 GiB. Intake stops at 512 MiB to
reserve room for compression and refuses when less than 64 MiB free remains.
Pending batches are never pruned to make room. The disk guard logs bytes, file count
and oldest pending age even when free disk already meets its target.

`ac-telemetry-raw <dev|staging|production>` runs every ten minutes. It closes old
hours, compresses closed files, reuses the root-owned installed `ac-archive-put`
helper's constrained Infisical credential loader (prod `/ops`, `AC_ARCHIVE_*`), and
uploads to:

```
s3://ac-archive-283923228069-apse2/lake/raw/<env>/analytics/dt=YYYY-MM-DD/HH-<host>-<seq>.ndjson.gz
```

It sends an explicit SHA-256 checksum and AES256 encryption, then verifies S3
ContentLength, ChecksumSHA256 and encryption. Only verification plus a locally
fsynced `.receipt` permits deletion of the original and compressed local files.
Failure retains the original. A crash retries the same object key. Receipts retain
opaque event IDs by occurrence day for reconciliation and expire after 10 days
(beyond the seven-day intake replay window), so successful archival does not leave
an ever-growing local identifier index. Historical manifest counts remain in S3.
S3's existing `lake/` lifecycle expires at 178 days, inside the 180-day notice.
No archive credentials enter argv, logs, source control or saved configuration.

## Heartbeat and Admin

The API's independent ASGI counters retain only ten-minute aggregate counts of
screen-originating API requests, telemetry requests, 5xx, accepted, hot-stored and
spooled observations. No request URLs, headers or identities are persisted in counters.
Counters live beside the journal; counters older than one day are removed.

`ac-telemetry-heartbeat` checks three completed ten-minute windows, every ten minutes:

- nonzero app traffic but zero accepted telemetry;
- telemetry 5xx above 1% (exactly 1% does not alarm);
- pending spool >=384 MiB or oldest pending file >2 hours;
- shipper failed or stale with pending data;
- reconciliation mismatch or missing traffic-counter stream.

It writes a content-free line to the ops journal and atomically publishes
`/var/lib/ac-telemetry-heartbeat/status.json`. Admin Telemetry and Speed show an
accessible alert with the problems and accepted/stored/spooled counts. Missing or
older-than-20-minute status is an alarm. The root runner ensures/updates the one HQ
task marked `orch:telemetry-heartbeat` via `ac-pulse-tasks`. Task-update failure is
logged, leaves the local alert active and fails the service for visibility. No Telegram.

A healthy run clears the banner; it leaves the HQ task available for investigation.
Historical alarm lines remain in the ops journal. The timer's journal is the ops log:
`journalctl -u ac-telemetry-heartbeat.service`.

## Nightly reconciliation and backfill

The analytics lake manifest includes `reconciliation.postgres_rows`, `raw_rows`,
`lake_rows` and `mismatch` for the UTC occurrence day, on dev and production.
Raw counts union event IDs from pending journals and verified-upload receipts;
retries do not inflate the raw count. Postgres counts use the export's consent/expiry
selection. Lake rows also observe current workspace/person collection preferences.
Thus privacy changes and ingestion lateness can produce a visible mismatch; counts
are diagnostic evidence, never authority to recreate deleted or opted-out events.
The latest reconciliation is also written beside the spool for the heartbeat.

Recovery is explicit and dry-run by default:

```
python -m ac_platform.telemetry.raw_cli backfill \
  --file /reviewed/closed.ndjson.gz \
  --database-url-file /reviewed/environment/database-url
```

Add `--apply` only for the approved target environment. The operator retrieves a
verified S3 object when the journal has already shipped. The worker uses the original
event IDs and repository replay checks, original retention expiry, current privacy
preferences and the person hot-store cap. Existing server call references are preserved
when comparing replays. Conflicting observations are counted and skipped, so one
rejected replay cannot prevent recovery of unrelated events. The default limit is 20,000 observations
per transaction; `--limit` may lower it. Dry-run rolls back. No raw file is deleted
by backfill, no expired observations are restored, and nothing updates canonical state.
Use the deployment's existing production data-change controls for any production run.

## Orchestrator activation checklist (reviewed units; not installed by builder)

1. The API creates its telemetry subdirectory under the already writable durable
   intake bind; no new mount is required to keep intake working. For explicit
   provisioning, create private host journal directories for each target environment, writable by
   the API UID (10001 in containers), plus `/var/lib/ac-telemetry-heartbeat` (0755).
   Dev host service uses its own service UID. Never share an environment's journal.
2. Include `infra/application/compose.telemetry-durable.yaml` in the reviewed release
   compose inputs. It binds the durable host journal read/write and heartbeat directory
   read-only. Its source is the same existing durable intake subdirectory, isolated
   by environment. For host dev, the existing durable storage bind is used. A truly
   unwritable or full journal correctly returns 503.
3. Install the reviewed current application package in the existing
   `/opt/ac-lake-export/.venv` used by the nightly exporter. Both CLI modules are in
   that package. The reviewed lake unit includes ReadWritePaths for the journal's reconciliation
   file while retaining ProtectSystem=strict.
4. Install the raw/heartbeat scripts root-owned in `/usr/local/sbin`, and the checked-in
   units/timers under `/etc/systemd/system`. Use existing archive bootstrap credentials;
   do not copy their values. Enable the appropriate raw instances and heartbeat timer
   after review. Timers are not installed or started by this change.
5. Send synthetic consented events on dev: normal, forced tiny hot cap, SQL failure,
   then disk refusal. Check receipts and 202/503 outcomes. Close an hour, run shipping,
   verify the S3 checksum/size receipt, and prove local deletion follows verification.
6. Check a nightly manifest and simulate each alarm threshold on fixture counters.
   Read the Admin banner and one marker-bound HQ task, then restore healthy fixtures.
   Staging/production activation follows the owner's normal release process.

The builder's tests use fictional data and fake S3/task commands. A real S3 upload,
production backfill, timer installation and deployment require operator evidence;
local green checks do not establish those operational results.
