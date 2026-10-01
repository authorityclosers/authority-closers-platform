# R2 cost-safety policy

## Enforced operating envelope

The owner approved paid Standard storage above the free 10 GB allowance on [AUT-10, 29 Sep 2026](/AUT/issues/AUT-10#comment-495303be-6aee-41ae-983f-d5520e8dc799). Operation ceilings remain below the free allowances. The local deployment envelope is:

| Dimension          |   Local ceiling | Published free allowance |
| ------------------ | --------------: | -----------------------: |
| Standard storage   | 100 GiB; warn at 75 GiB |   10 GB-month/month |
| Class A operations |   700,000/month |          1,000,000/month |
| Class B operations | 7,000,000/month |         10,000,000/month |
| Infrequent Access  |         0 bytes |             No free tier |

The 30% operation headroom absorbs metric delay, retries, probes, and administrative operations. R2 usage above the included amounts is billed; Cloudflare does not expose a hard free-tier usage stop. At $0.015/GB-month after 10 GB free, about 21 GB stored costs $0.165 (about $0.17/month), and 100 GiB = 107.3741824 GB costs about $1.46/month before billing-unit rounding (about $1.47 with rounding), assuming steady storage for a full month and no other account usage.

The required warning line is 80,530,636,800 bytes (75 GiB), below the 107,374,182,400-byte (100 GiB) ceiling. It counts **stored** Standard bytes only. Only the 30-minute `ac-r2-usage-guard.service` sets `R2_WARN_IS_FAILURE=1`, making a warning visible in failed units; backup callers continue through warnings. Hard storage/projection limits and operation checks still fail closed. At the hard ceiling the shared projection guard stops **every off-host backup, including the database**; the unchanged 5.25 GiB logical reservation can refuse writes earlier.

## Current charge-safe state

- R2 billing is active.
- Two private Standard buckets exist: `authority-closers-backups-prod` and `authority-closers-objects-prod`.
- The last planning observation supplied for this change was approximately 366,540 Standard bytes on 2026-08-30; the exact current value must come from the fail-closed metrics guard and is never hardcoded by the writer.
- No R2 provider credentials are stored on the VPS outside short-lived process environments; the Infisical bootstrap contains only machine-auth values.
- Daily Restic backup, a 30-minute R2 usage guard, and a weekly isolated repository restore drill are enabled. Application uploads, public bucket domains, R2 Data Catalog, R2 SQL, Sippy, Super Slurper, and migration jobs are disabled.
- The backup credential is restricted to the two AC buckets and the VPS IPv4 address. Infisical injects it only into the bounded operational processes.
- Application database state, verified logical dumps, deployment evidence, and configuration remain in the encrypted backup source. Reproducible application release directories and compressed Docker transport bundles are excluded: those large artifacts remain in private GHCR and the local VPS rollback store, and can be reconstructed from the exact Git SHA plus registry digest. This prevents routine releases from consuming the R2 storage envelope with duplicate image data.
- The logical PostgreSQL writer is implemented but remains disabled until the separate `activate postgres-backup` gate passes. It captures each healthy current application release using its exact release profile and compose project; a missing production current link is skipped, while an unhealthy present production link fails closed.

This is a bounded active-writer state, not a zero-writer state. Every off-host write fails closed unless the usage guard can prove the remote envelope remains safe. The logical writer can retain a verified, bounded local capture during that failure and still returns nonzero. Foundation retention is 7 daily, 4 weekly, and 6 monthly snapshots: deleted recordings and videos can remain in monthly snapshots for up to six months. Logical application snapshots are tagged separately, retained for a 27-hour window, and pruned only by the daily foundation job.

## Logical PostgreSQL storage and operation model

The committed initial model in `config/r2/free-tier-policy.conf` bounds each custom-format dump at 8 MiB, retains 336 points per environment, and reserves for two environments. The worst-case logical retained payload is therefore:

`8 MiB × 336 points × 2 environments = 5,637,144,576 bytes (5.25 GiB)`

Local disk additionally permits one in-flight capture per environment, each bounded to 8 MiB plus its metadata. A failed post-capture retention pass can leave that one extra pair (337 per environment); a later run validates the ring before capture and refuses further accumulation. Cleanup can finish a previously renamed prune directory, but preflight never guesses which complete pair to discard from an overfull ring. This local exception adds at most 16 MiB of dump payload across two environments and does not increase the off-host projection, quota thresholds, cadence, or allowed request budget. The exact new pair is protected during post-capture retention even after a backward wall-clock adjustment.

This is a conservative payload projection; Restic deduplication may use less storage, but it is not relied on. Before every logical off-host write, the R2 guard queries current Standard storage and rejects when `current usage + 5.25 GiB` is above the local 100 GiB ceiling. The guard does not hardcode the observed approximately 366,540 bytes; it queries the live metrics API. If a compressed database dump approaches 8 MiB, the job fails closed: migrate to a reviewed continuous-WAL/PITR system or explicitly revise the capacity plan instead of silently increasing the bounded writer.

At 5-minute cadence the theoretical maximum is 288 captures per day per active environment, or 17,280 captures per 30-day month for two environments. Exact Class A cost depends on Restic's object layout and retries, so the existing 700,000/month Class A guard remains authoritative and is run before each off-host write. No Cloudflare hard billing cap is implied. The five-minute cadence, 30-second jitter, four-minute dump timeout, and four-minute upload timeout leave a bounded healthy-run window inside the 15-minute objective; any failed or skipped run is an RPO incident, not a reason to claim the target still passed.

## Foundation projection, cache and maintenance (AUT-163)

All four backup/restore entrypoints require `/var/cache/authority-closers-restic` to be a real, root-owned directory and create/remove a probe there before any restic request. Missing, symlinked or unwritable caches fail with `AC_BACKUP_FAILURE=restic_cache_unavailable`. A restic `unable to open cache` warning also fails the run. Units provision the shared directory using `CacheDirectory=authority-closers-restic` and `CacheDirectoryMode=0750`; explicit writable paths remain. The logical restore proof uses an inline temporary wrapper to detect warnings hidden by Python's child-stderr suppression; it removes the wrapper on exit and stores no credentials in it.

Under the host flock, the daily job runs: guard with projection **0**, stale-only `unlock`, logical `forget --group-by host,tags --keep-within 27h`, foundation `forget` (7 daily / 4 weekly / 6 monthly), then `prune`. Maintenance therefore completes before a refused foundation snapshot. The zero projection removes only the extra foundation reservation; the guard still applies its unchanged logical reservation and account-wide checks. A failed first guard makes no restic request. Stale-only unlock preserves live locks; contention or any maintenance failure stops the job.

Foundation admission then uses `restic backup --dry-run --json` with exactly the real backup's sources and exclusions. Exactly one summary must contain a nonnegative integer `data_added`; a failed dry-run, absent summary or malformed value refuses the write. This is new **uncompressed** blob data, including tree metadata, rather than the entire source size; no compression credit is taken. It is passed as `R2_PROJECTED_ADDITIONAL_BYTES` to the second guard. Source changes between projection and capture and delayed provider metrics remain limitations of preflight admission.

The existing secrets, application artifacts/releases and local logical-ring exclusions stay. Additional exclusions are limited to rebuildable material:

| Excluded path below `/srv/authority-closers` | Reason |
| --- | --- |
| `release-store/*`, with ordered re-inclusion of `release-store/native` | Rebuildable transport bundles; native zips remain because GitHub expires them after a day. |
| `media-safety/scanner-temp-v1.ext4` | 8 GiB scanner scratch image. |
| `volumes/media-safety-tmp` | Scanner temporary files. |
| `volumes/media-safety-signatures` | Signatures refreshed by freshclam. |
| `volumes/media-video/*/tmp` | FFmpeg scratch. |
| `sales-xray/*/scratch` | Rebuildable processing scratch. |

Native archives, video/avatar objects, `sales-xray/*/storage` recordings and `application/operator-inputs` stay included.

Expected requests with a warm cache and no retries (operation counts vary with object sizes, pagination, live locks and cache warming):

| Run | Expected Class A | Expected Class B |
| --- | --- | --- |
| One 5-minute logical upload per environment | LIST keys/locks/snapshots/indexes; PUT lock, snapshot, new index objects and data/tree packs. No forget/prune. For two environments, two such calls; 288 calls/day/environment. | Config/key HEAD/GET, live-lock reads and newly encountered metadata. **Zero repeated GETs of cached historical snapshot/index objects**, instead of two reads per earlier capture. |
| One daily foundation run | Six restic calls: unlock, two forgets, prune, dry-run and backup. LISTs and maintenance locks plus PUTs for repacked packs/indexes and new foundation objects. Dry-run writes no objects or repository lock. | Config/key and lock reads per call; metadata cache misses; prune GETs for retained trees and packs selected for repacking. Cached snapshots/indexes are reused. |

Prune is not request-free: it lists packs, scans retained trees, downloads partially used packs when repacking, uploads replacement packs/indexes, then deletes obsolete objects. DELETE operations are free under R2's published pricing. Refusal at the second guard omits the sixth call (real foundation backup), after maintenance and dry-run have completed. A cold cache can read the retained set once; it must not repeat that download on every five-minute run. Post-install R2 observations must establish the actual per-run counts; these expectations do not replace the existing operation ceilings.

## Media capacity evidence (AUT-186)

The first foundation snapshot is expected to add about 20 GB of media from the [AUT-10 measurements](/AUT/issues/AUT-10), plus other included sources and metadata. With restic 0.16.4's default 16 MiB target packs, `ceil(20,000,000,000 / 16,777,216) = 1,193` data-pack PUTs is an approximate Class A baseline, plus tree/index/snapshot/lock PUTs, LISTs, maintenance, retries and any multipart requests. No measured compression saving or pack-size override is assumed; the existing 700,000/month Class A cutoff stays authoritative.

The [0.16.4 FAQ](https://restic.readthedocs.io/en/v0.16.4/faq.html#will-restic-resume-an-interrupted-backup) says reruns reuse indexed uploaded data and rescan files until a first snapshot exists. However, this job runs `prune` before every backup. Prune removes data unreferenced by retained snapshots, so a `TimeoutStartSec=90min` interruption can lose upload progress on the next scheduled run. Existing completed snapshots and source media survive; a completed new snapshot is not guaranteed. **CTO decision required before merge** on this first-upload retry risk; this task changes neither timeout nor maintenance order.

Fictional retention-v2 sizing from [AUT-628](/AUT/issues/AUT-628#document-media-sizing): `10 calls/day × days × 1,800 seconds × bitrate × 1,000 / 8 / 2^30` GiB. Count identical live bytes across snapshots once; add 180 days of distinct deleted audio and illustrative 20 GB existing media, without compression credit:

| Bitrate | 730-day live audio | Live + 180-day backup-only tail + 20 GB media |
| --- | ---: | ---: |
| 32 kbit/s | 48.95 GiB | 79.65 GiB |
| 128 kbit/s | 195.80 GiB | 262.71 GiB |

These totals exclude other stores and overhead. The lower forecast already exceeds the 75 GiB warning; the higher exceeds the 100 GiB hard limit and threatens database backups too. The six-month backup window and separate 32 GiB acquisition cap remain unchanged. Capacity beyond 100 GiB needs a separate owner-approved decision through the CEO.

## Deployment gate

No R2 writer may be enabled unless all of the following are true:

1. `scripts/r2-usage-guard.sh` passes with a rotated token that can read R2 metrics and GraphQL analytics.
2. The writer has an Object Read & Write credential scoped to one required bucket, not account-admin rights and not all future buckets.
3. Upload size, request rate, retry count, and retention are bounded by the application or backup job.
4. A reversible `scripts/r2-probe.sh` test passes and leaves no object behind.
5. Cloudflare account budget alerts are configured. Budget alerts notify; they do not stop usage.

Any API failure, unknown operation class, Infrequent Access byte, or local-threshold breach is a failed deployment gate. The guard deliberately fails closed.

## Backup activation rule

Restic was activated only after a reversible object probe, metrics guard, repository initialization, encrypted snapshot, off-host passphrase escrow, bounded retention, and restore drill passed. Any new backup source or writer requires a fresh size/operation model and must remain disabled until the same evidence is produced. If the retained set cannot remain below the envelope, obtain explicit approval for paid R2 usage or choose a different backup target.

The logical PostgreSQL writer has an additional explicit gate. The reviewed host must have exact installed service/timer units, a current R2 usage pass, a dry-run of release/profile/health and projection checks, and a capture-only run that completes `pg_restore --list` verification. The gate enables only `ac-postgres-backup.timer`; it does not claim that the writer is active until the operator performs that command on the host and observes successful snapshots.

## Important limitation

No client-side script can guarantee a Cloudflare account never incurs a charge if another credential, Worker, dashboard user, migration tool, or direct S3 client bypasses it. The strongest current control is a narrow credential, IP restriction, bounded retention, frequent metrics checks, and a fail-closed preflight before every scheduled write. Rotate any credential exposed outside Infisical and do not issue unguarded production keys.

## Official references

- Cloudflare R2 pricing: <https://developers.cloudflare.com/r2/pricing/>
- R2 metrics and GraphQL datasets: <https://developers.cloudflare.com/r2/platform/metrics-analytics/>
- Cloudflare usage-based billing: <https://developers.cloudflare.com/billing/understand/usage-based-billing/>
- Cloudflare R2 lifecycle behavior: <https://developers.cloudflare.com/r2/buckets/object-lifecycles/>

- Restic 0.16.4 [dry-run and exclusion rules](https://restic.readthedocs.io/en/v0.16.4/040_backup.html), [cache](https://restic.readthedocs.io/en/v0.16.4/100_references.html#local-cache) and [prune](https://restic.readthedocs.io/en/v0.16.4/060_forget.html#customize-pruning).
