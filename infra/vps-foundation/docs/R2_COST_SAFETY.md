# R2 cost-safety policy

## Enforced operating envelope

Authority Closers treats Cloudflare's published free allowance as an outer boundary, not a target. The local deployment ceiling is:

| Dimension | Local ceiling | Published free allowance |
|---|---:|---:|
| Standard storage | 8 GiB | 10 GB-month/month |
| Class A operations | 700,000/month | 1,000,000/month |
| Class B operations | 7,000,000/month | 10,000,000/month |
| Infrequent Access | 0 bytes | No free tier |

The 30% operation headroom and storage headroom absorb metric delay, unit differences, retries, probes, and administrative operations. R2 usage above Cloudflare's included amounts is billed; Cloudflare does not expose a hard free-tier usage stop.

## Current charge-safe state

- R2 billing is active.
- Two private Standard buckets exist: `authority-closers-backups-prod` and `authority-closers-objects-prod`.
- The encrypted foundation backup retained approximately 353 KB at the 2026-08-30 audit; the exact current value must come from the fail-closed metrics guard.
- No R2 provider credentials are stored on the VPS outside short-lived process environments; the Infisical bootstrap contains only machine-auth values.
- Daily Restic backup, a 30-minute R2 usage guard, and a weekly isolated repository restore drill are enabled. Application uploads, public bucket domains, R2 Data Catalog, R2 SQL, Sippy, Super Slurper, and migration jobs are disabled.
- The backup credential is restricted to the two AC buckets and the VPS IPv4 address. Infisical injects it only into the bounded operational processes.

This is a bounded active-writer state, not a zero-writer state. Every scheduled backup fails closed unless the usage guard can prove the local envelope remains safe. Retention is 7 daily, 4 weekly, and 6 monthly snapshots.

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

## Important limitation

No client-side script can guarantee a Cloudflare account never incurs a charge if another credential, Worker, dashboard user, migration tool, or direct S3 client bypasses it. The strongest current control is a narrow credential, IP restriction, bounded retention, frequent metrics checks, and a fail-closed preflight before every scheduled write. Rotate any credential exposed outside Infisical and do not issue unguarded production keys.

## Official references

- Cloudflare R2 pricing: <https://developers.cloudflare.com/r2/pricing/>
- R2 metrics and GraphQL datasets: <https://developers.cloudflare.com/r2/platform/metrics-analytics/>
- Cloudflare usage-based billing: <https://developers.cloudflare.com/billing/understand/usage-based-billing/>
- Cloudflare R2 lifecycle behavior: <https://developers.cloudflare.com/r2/buckets/object-lifecycles/>
