# Local backup continuity repair — 2026-09-11

Status: source candidate; not installed or represented as live backup recovery.

## Trigger and controlled scope

Read-only VPS inspection verified installed foundation release
`74631e0dd94a1d54a2e2b88bc925e47e0e0c7029`, its complete release manifest,
and sampled installed scripts against source. The logical backup job failed
at its R2 guard before capturing locally. The Class B guard reported its
saturated `7000001` sentinel above the `7000000` ceiling; the sentinel is not
an exact operation count. The most recent paired logical capture remained
`20260910T071540.451126Z-3902007-staging`, release
`4e8d413b828ab750d7c5e20d1a9320d0f427c823`, migration `20260910_0027`, parity v7.

This change addresses recovery continuity under AC-IMP-03 P0-03/P0-07,
AC-IMP-05 ENG-G08, DevOps and QA recovery evidence requirements. It does not
change R2 limits, enable another writer, bypass repository locking, or make
a local capture satisfy an off-host restore/RPO gate. Controlled source IDs
are recorded in the companion release recovery checkpoint.

## Resulting behavior

- Verify the bounded root-owned local ring under the environment lock before
  creating the next atomic dump/metadata pair.
- Capture and verify locally before the R2 guard; perform the guard under the
  repository lock immediately before any off-host upload.
- Keep `--capture-only` independent of R2. Keep ordinary dry-run R2 validation;
  the combined dry-run/capture-only mode performs no local or remote writes.
- Preserve the exact new pair during retention, even if CLOCK_REALTIME moved
  backward. If retention fails, the next run preserves an overfull ring and
  refuses another capture; it does not choose a victim by ambiguous timestamps.
- Continue other already-resolved healthy environments after a bounded
  capture/upload failure, then report an aggregate nonzero result. Curated
  errors state when a verified local pair exists; filesystem/subprocess
  diagnostics and synthetic sensitive command/output text are not exposed.

The unchanged limit is 336 retained captures per environment and 8 MiB per
dump. A failed retention pass may leave one extra pair per environment;
preflight prevents repeated growth. The remote 5.25 GiB payload projection
and all quota/cadence settings remain unchanged. Snapshot parity and the
dump/metadata format are unchanged.

## Validation

Initial focused run: 51 passed, 13 skipped on Windows. The skips require
POSIX shell/flock; they must pass in Linux CI before release. Independent
review identified the clock rollback plus failed-prune retry edge after
that run; a two-run regression and validation-only preflight were added.
Final regression rerun: **52 passed, 13 skipped in 1.02 seconds**. The added
regression spans a backward-clock capture, failed offsite guard and prune,
then a recovered next run; the freshest pair remains intact and no new
capture is allowed while the complete ring is over its bound. Independent
source review cleared the final delta with no remaining actionable findings.
Reviewed SHA-256: controller
`7e7049de5f3821e68b0bcbad5b3c4bb1595c4b53cdf1c912e40d5c2108244b03`;
tests `17f4891b09dd8bad0751cc936626f398f33acb4ac44bc5a515287cc69d824b96`.

Ruff check and format verification passed on the updated code and tests.
No live backup capture, upload, retention repair, timer activation or
foundation installation has been performed by this candidate.

## Release acceptance still required

Independent clearance, exact source commit and Linux CI; immutable foundation
archive/manifest and installed-file proof; bounded live local capture with
paired SHA-256, migration/parity metadata, permissions and retention count.
The saturated R2 quota remains a separate failed offsite capability gate.
The 0027-to-0029 disposable rehearsal still requires independently attested
old/new images and paired backup evidence; this repair does not execute it.
