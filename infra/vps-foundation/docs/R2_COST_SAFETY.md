# R2 cost-safety policy

## Enforced operating envelope

Authority Closers treats Cloudflare's published free allowance as an outer boundary, not a target. The local deployment ceiling is:

| Dimension          |   Local ceiling | Published free allowance |
| ------------------ | --------------: | -----------------------: |
| Standard storage   |           8 GiB |        10 GB-month/month |
| Class A operations |   700,000/month |          1,000,000/month |
| Class B operations | 7,000,000/month |         10,000,000/month |
| Infrequent Access  |         0 bytes |             No free tier |

The 30% operation headroom and storage headroom absorb metric delay, unit differences, retries, probes, and administrative operations. R2 usage above Cloudflare's included amounts is billed; Cloudflare does not expose a hard free-tier usage stop.

## Current charge-safe state

- R2 billing is active.
- Two private Standard buckets exist: `authority-closers-backups-prod` and `authority-closers-objects-prod`.
- The last planning observation supplied for this change was approximately 366,540 Standard bytes on 2026-08-30; the exact current value must come from the fail-closed metrics guard and is never hardcoded by the writer.
- No R2 provider credentials are stored on the VPS outside short-lived process environments; the Infisical bootstrap contains only machine-auth values.
- Daily Restic backup, a 30-minute R2 usage guard, and a weekly isolated repository restore drill are enabled. Application uploads, public bucket domains, R2 Data Catalog, R2 SQL, Sippy, Super Slurper, and migration jobs are disabled.
- The backup credential is restricted to the two AC buckets and the VPS IPv4 address. Infisical injects it only into the bounded operational processes.
- Application database state, verified logical dumps, deployment evidence, and configuration remain in the encrypted backup source. Reproducible application release directories and compressed Docker transport bundles are excluded: those large artifacts remain in private GHCR and the local VPS rollback store, and can be reconstructed from the exact Git SHA plus registry digest. This prevents routine releases from consuming the R2 storage envelope with duplicate image data.
- The logical PostgreSQL writer is implemented but remains disabled until the separate `activate postgres-backup` gate passes. It captures each healthy current application release using its exact release profile and compose project; a missing production current link is skipped, while an unhealthy present production link fails closed.

This is a bounded active-writer state, not a zero-writer state. Every off-host write fails closed unless the usage guard can prove the remote envelope remains safe. The logical writer can retain a verified, bounded local capture during that failure and still returns nonzero. Foundation retention is 7 daily, 4 weekly, and 6 monthly snapshots. Logical application snapshots are tagged separately, retained for a 27-hour window, and pruned only by the daily foundation job.

## Logical PostgreSQL storage and operation model

The committed initial model in `config/r2/free-tier-policy.conf` bounds each custom-format dump at 8 MiB, retains 336 points per environment, and reserves for two environments. The worst-case logical retained payload is therefore:

`8 MiB × 336 points × 2 environments = 5,637,144,576 bytes (5.25 GiB)`

Local disk additionally permits one in-flight capture per environment, each bounded to 8 MiB plus its metadata. A failed post-capture retention pass can leave that one extra pair (337 per environment); a later run validates the ring before capture and refuses further accumulation. Cleanup can finish a previously renamed prune directory, but preflight never guesses which complete pair to discard from an overfull ring. This local exception adds at most 16 MiB of dump payload across two environments and does not increase the off-host projection, quota thresholds, cadence, or allowed request budget. The exact new pair is protected during post-capture retention even after a backward wall-clock adjustment.

This is a conservative payload projection; Restic deduplication may use less storage, but it is not relied on. Before every logical off-host write, the R2 guard queries current Standard storage and rejects `current usage + 5.25 GiB` above the local 8 GiB ceiling. The guard does not hardcode the observed approximately 366,540 bytes; it queries the live metrics API. If a compressed database dump approaches 8 MiB, the job fails closed: migrate to a reviewed continuous-WAL/PITR system or explicitly revise the capacity plan instead of silently increasing the free-tier writer.

At 5-minute cadence the theoretical maximum is 288 captures per day per active environment, or 17,280 captures per 30-day month for two environments. Exact Class A cost depends on Restic's object layout and retries, so the existing 700,000/month Class A guard remains authoritative and is run before each off-host write. No Cloudflare hard billing cap is implied. The five-minute cadence, 30-second jitter, four-minute dump timeout, and four-minute upload timeout leave a bounded healthy-run window inside the 15-minute objective; any failed or skipped run is an RPO incident, not a reason to claim the target still passed.

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
