# AUT-1580: bounded edge projection recovery for AUT-1572

Source baseline: `ca5a4a060f2e2f617cf25ccee71f541ef75f2aa9`.
Task branch: `task/devenv/1580-edge-projection-recovery`.
Operator run: `22320349-6d8b-4451-87bc-718815f2eae1`.

## Live reconciliation before implementation

The original drift was already cleared before this run started implementation.
These read-backs do **not** establish the operator or authorization of the
intervening repair. They do not represent execution of the new command.
AUT-1572's existing receipt at 19:54–20:00 UTC on 8 October separately records
the cleared predecessor comparisons, staging resume at 18:47:17Z, and automatic
staging/core success at `bcd1d53` beginning 18:48:20Z. Reconciliation of that
intervening operation remains on AUT-1572.

At 23:51–23:53 UTC on 8 October 2026, all of these commands exited 0:

- `sudo -n /usr/local/sbin/ac-root check`: live run permitted to use root.
- `sudo -n /usr/local/sbin/ac-root run -- /usr/local/sbin/ac-release status --json`:
  both cores were `df769bac0ddb5d70880a0db382834503fb4c149e`; both web releases
  were `06360db921f5b7ecb60d05df29d59752294a2122`, image
  `sha256:1d1b6bf385b738c2d2318b6d4c75e125669c42272b275d90b8c82f263d47d6bb`.
  Both environments had paused=false and no failed core/web flag. Staging
  auto_deploy=true; production auto_deploy=false. The installed engine remained
  `77096486a08be3f2c2c93fff4e732baa8dba8ed9`.
- Audited `ac-root run -- /usr/bin/python3 -c ...` bounded readers verified full
  manifests and regular public projections, and returned only metadata, hashes,
  selector targets and containment filenames. No credential values were read
  into the report. Both current core and public route selectors pointed at
  `df769bac0ddb5d70880a0db382834503fb4c149e`.
- Public readiness GETs: staging at 23:53:02Z and production at 23:53:04Z each
  returned HTTP 200/status ready, with body and `X-AC-Release-Id` equal to
  `df769bac0ddb5d70880a0db382834503fb4c149e`; routes were api-staging and
  api-production respectively.
- `git merge-base --is-ancestor 77096486a08be3f2c2c93fff4e732baa8dba8ed9 df769bac0ddb5d70880a0db382834503fb4c149e`:
  exit 0.

| Owner release | Manifest SHA256 | Entries verified |
| --- | --- | --- |
| `99e8934ed530a67f90dd7dac76888580de57fbf9` | `fd1f7b71039d78310bd19e088d2fe611f03501df9917fce6dcf712426cf9e0e0` | 82/82 |
| `df769bac0ddb5d70880a0db382834503fb4c149e` | `49f5109aa423321752fb487926439e5db2eaa61f3e84456dd32dd5eb286e0c02` | 82/82 |

Every projection below was root:root 0444 and matched its immutable owner:

| Owner | Projection | Observed and owner SHA256 |
| --- | --- | --- |
| `99e8934` | production | `a9cfd450e34757994781e9fc7f414a177753422aad85405751d6dc9b9bfff7cc` |
| `99e8934` | staging | `d632b5022473059d7d8a8eba46230d62faa266f908797ee8c1d53e9cf10ea4da` |
| `df769bac` | production | `f9a4f52d22e04a08f6fdcf9c00b08bec6ce5741207a85887182e336fcc463d4e` |
| `df769bac` | staging | `6fb46e1f75294d5986e088d0cd361ab48be2f332056b27022674274649cc4cb2` |

No HELD, paused or component failed file was found in the two release control
roots. The existing `train-failed` directory and historical last-train failure
were retained. No release apply, resume, pause, tick, engine install, service
action, secret change, data change or projection write was performed in this run.

## Source operation

The implementation is inside `infra/release/ac_release.py`, which the existing
installer already ships. No installer, workflow, route source or helper loading
change is needed. Only the original owner, full manifest digest/count, and exact
two before/after route digests are admitted. There is no caller-supplied drift
allowlist or option to bypass verification.

Rehearsal opens **existing** release and deployment locks read-only and locks
them without waiting. It creates no lock, audit directory or output file. The
plan binds full owner-file verification, trusted parent identities, exact
selectors, root-owned regular inputs, public and hold metadata, containment and
history, activation/approval/service/native hashes, native unit state/files, and
running core/web/edge container identities. Configured core images must agree
with the owner's verified image manifest. No container environment is inspected.

Apply requires the digest of that exact plan. All original public bytes and the
plan are durably written and read back before replacement. Each public file is
atomically replaced through verified directory descriptors, remains root:root
0444, and is checked again. Completed receipts include after metadata. Original
release/history, selectors, hold projections, flags and bindings are never
written. No service is started or reloaded. Receipts use exclusive file creation,
0444 files and a sealed 0555 completed directory beneath the root-only state
directory. Interrupted atomic stages are immutable files outside the four-file
projection directory; they are retained if a process dies before rename.

Catchable write failures compensate only recognized owner bytes, using verified
backups. Unexpected concurrent bytes are preserved and rejected. A prepared
receipt without completion cannot be replayed by apply. The supported rollback
can compensate a process death or interrupted rollback and records a separate
receipt; it never overwrites the original audit evidence. Repeat apply and
rollback verify their completed receipts and current metadata before returning
without writes. A rolled-back plan is not permission to reapply it.

## Invocation and containment contract

Source merge requires CTO review and CEO approval of the exact PR head. Source
installation remains the normal release-engine operation. This document grants
no live repair authority. Only a named Root operator with CTO/CEO approval of
the concrete plan may use apply or explicit rollback:

```sh
sudo -n /usr/local/sbin/ac-root run -- /usr/local/sbin/ac-release recover-edge-projections --owner-release 99e8934ed530a67f90dd7dac76888580de57fbf9 --dry-run
# Review the returned two-file plan and record approval of PLAN_SHA256.
sudo -n /usr/local/sbin/ac-root run -- /usr/local/sbin/ac-release recover-edge-projections --owner-release 99e8934ed530a67f90dd7dac76888580de57fbf9 --apply --plan-sha256 PLAN_SHA256
# Explicit failure compensation, only under the recorded repair/rollback authority:
sudo -n /usr/local/sbin/ac-root run -- /usr/local/sbin/ac-release recover-edge-projections --owner-release 99e8934ed530a67f90dd7dac76888580de57fbf9 --rollback --plan-sha256 PLAN_SHA256
```

Receipt root: `/var/lib/ac-release/edge-projection-recovery/PLAN_SHA256`.
Rollback receipt: the sibling `PLAN_SHA256-rollback` directory. Verify both
projection hashes, readiness, selectors and all before/after bindings. If
verification or rollback refuses, stop and record the precise mismatch while
retaining containment. Do not manually edit a route, delete a receipt, re-seal
an owner, restart a service, clear a flag or tick/deploy to force progress.
Rollback restores the recorded drift and can restore the installer blocker.
AUT-1572 alone owns the separate guarded staging resume and automatic delivery.

**Current host state is outside this original repair's pins.** Its selectors
already advanced and its predecessor projections already match. The command must
refuse that state without writes. Never roll the host back or recreate drift to
obtain an apply receipt. CTO/CEO review must reconcile this card's original live
acceptance with the already-cleared condition; source work is not a live repair
receipt and this card is not complete on source approval.

## Verification

```sh
.venv/bin/python -m pytest tests/infra/test_ac_release_edge_repair.py tests/infra/test_ac_release.py tests/infra/test_ac_release_train.py tests/infra/test_ac_release_admin.py -q --tb=short
.venv/bin/ruff check infra/release/ac_release.py tests/infra/test_ac_release_edge_repair.py
.venv/bin/ruff format --check infra/release/ac_release.py tests/infra/test_ac_release_edge_repair.py
git diff --check
ac-gate check
```

Focused release-engine suite: **380 passed**. Final recovery suite: **42 passed**.
Ruff lint and format checks pass. Lane check: exit 0, this task branch may be
worked on. Tests use fictional public routes and bindings, with no customer,
provider, secret or database access. They cover exact apply, absence of dry-run
mutations, changed selectors/core/images/holds/manifest/metadata, escapes,
symlinks/hardlinks, missing and busy locks, changed plans and concurrent drift,
durable audit/backup preservation, interruption after staging or rename, safe
compensation, interrupted explicit rollback, corrupt/incomplete receipts, and
repeat apply/rollback. Process-death tests terminate a fork before compensation,
then exercise the supported rollback from its retained prepared receipt.

Repository CI, source merge/installation, managerial reconciliation of the
cleared live condition, and any separately approved live invocation remain open.

## CTO correction: final public-route digest verification

Review baseline: PR #412 at `52e56cf0d80c28e6c61ac97d159652c0b66a4438`.
Correction run: `12fca629-0568-4be6-8661-80d57496fdb7`, 9 October 2026 UTC.
The CTO's P1 finding was reproduced locally before changing the implementation:
all **8** new fictional race cases failed because apply or rollback returned
success instead of rejecting concurrent public-route drift.

Both completion paths now compare **both** collected public-route digests with
the required pins before creating `completed.json`: immutable owner hashes for
apply and verified backup hashes for rollback. A mismatch raises an error.
Apply then follows its existing compensation/containment path, replacing only
recognized owner bytes and refusing unknown drift. Rollback retains its prepared
receipt without declaring completion. Neither path overwrites unknown bytes;
the original plan, prepared evidence and verified backups remain available.
No failure receipt is forced over the existing unknown-drift containment refusal.

The eight regression cases exercise apply and rollback after the first
replacement, after the last replacement (the CTO's reproduction), and just
before completion with drift in either public projection. They assert rejection,
absence of a completion receipt for the failed operation, preservation of unknown
bytes and original backups, unchanged original apply evidence during rollback,
preserved bindings/holds, and mutation-free refusal of a subsequent rollback.

The full focused release-engine suite passed **388 tests in 88.37s** (exit 0),
including all **50** recovery tests. Ruff lint/format checks, `git diff --check`
and the final lane check each exited 0. The verification commands remain the
ones listed above; no broader workspace test or live activation was used.

```sh
# At the review baseline with only the new regression tests: 8 failed.
.venv/bin/python -m pytest tests/infra/test_ac_release_edge_repair.py -k final_projection_drift -q --tb=short
# After the correction: 50 passed in 8.06s.
.venv/bin/python -m pytest tests/infra/test_ac_release_edge_repair.py -q --tb=short
```

The Root `main` checkout was clean and fast-forward synchronization reported
already up to date. The existing devenv task checkout was clean at the review
baseline; `ac-gate check` permitted this task (exit 0). Only the prescribed
source, recovery tests and this evidence document changed. This correction run
performed no host repair, release invocation, installation, service action or
new live read-back. The earlier live reconciliation remains historical evidence,
and the review/approval/installation/Root-verification gates above still apply.
