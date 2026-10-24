# Design: rehearse release migrations on the server, not through a GitHub schema artifact (24 Oct 2026)

Status: design for CTO review and CEO approval. It touches Root-governed release tooling: `ac-ship`,
`.github/workflows/migration-safety.yml` and the AUT-1741 publication runbook.

Owner, 24 Oct 2026: "why does it block things so often ... if root is blocking ... do something about it". The full
report is `docs/ops/release-pipeline-blockers-20261024.md`, row 4.

## Problem

Every release that adds a migration needs `AC_MIGRATION_SCHEMA_ARTIFACT_ID`, which must point at a staging schema
export that is at most 24 hours old and at main's migration head. Root publishes it by hand, in eight governed steps:
- an included-allowance receipt
- the export
- a git blob
- a workflow dispatch
- a read-back
- the repository variables
- the receipt
- the card

The artifact lives one day. Publication first needs a complete inventory of the 2 GB shared artifact pool, which holds
5,842 artifacts across 59 pages. That inventory is refused whenever any workflow uploads, or any artifact expires,
while the pages are being read (AUT-2066, AUT-2185). Four P0 Root cards have been raised for this since 16 Oct:
- AUT-2025, done.
- AUT-2065/2066, done.
- AUT-2177, blocked since 21 Oct.
- AUT-2214, blocked today. It is the only thing holding v0.87, and its next allowed attempt is 10:50Z.

## Options

| Option | Verdict |
|---|---|
| A. Automate the existing governed publication after every staging deploy | Rejected. It keeps every dependency that fails today: the complete-inventory guard over a pool that other workflows change all the time, the one-day retention, the 24-hour age limit and the allowance receipt. It would fail the same way, only unattended |
| B. Commit the staging schema to git for the PR to read | Rejected. The PR would supply its own evidence, so editing the file would bypass the check |
| **C. Rehearse where the schema lives (proposed)** | `ac-ship` already runs as root on ac. It exports staging's schema with the existing exporter, then runs the existing gate, unchanged, on the release commit while PR CI runs. The merge waits for both. GitHub's `migration-safety` rehearses on a baseline built from the migrations, so it needs no artifact |

## Design (phase 1, built with this card)

1. **`infra/release/rehearse-staging-migrations.py`** (new, root only, with tests). Its inputs are the workbench path, the candidate SHA and the base SHA, where the base is `origin/main`, the PR base.
   - If `db/migrations` is unchanged between base and candidate, it prints `PASS (no migration changes)` and does nothing else.
   - Otherwise it makes a root-owned `--no-hardlinks` clone of the workbench (64 MB) in a 0700 directory under `/var/tmp`, checks out the candidate and runs `uv sync --frozen`.
   - It runs `scripts/ops/export_migration_schema.py --apply`, the AUT-1741 exporter, unchanged. The exporter is staging only and root only. It uses the backup role's existing credential transport, takes a REPEATABLE READ snapshot, and produces a schema-only dump of at most 32 MiB, written to files with mode 0600. It reads staging's schema and changes nothing.
   - It runs `scripts/ci/migration_schema_gate.py --base-ref <base> --artifact-dir <export> --manifest-sha256 <sha256 of the manifest>`, also unchanged. That keeps the same evidence contract: manifest fields, revision equal to the PR base head, age within 24 hours, the same PostgreSQL major version, the TOC check, and the upgrade, downgrade, compare and re-upgrade rehearsal. The gate runs under `nice -n 10`, `ionice -c3` and a 15-minute timeout, with an environment that drops `AC_*`, `PG*`, `INFISICAL*`, `GH_TOKEN` and `GITHUB_TOKEN`.
   - It writes a receipt to `/var/lib/ac-release/schema-rehearsal/<candidate>-<UTC>.json`. The receipt records the candidate, the base, the staging release, the revision, the manifest and dump SHA-256s, the gate's one result line and the timings, but never schema contents. It then deletes the clone and the dump.
   - It prints one line, `schema-rehearsal: PASS|FAIL (<reason>)`, and exits 0 or 1. Any failure to export or rehearse stops the release; nothing is skipped.
2. **`ac-ship`**: when the release changes `db/migrations`, it starts the rehearsal in the background right after it pushes the release branch, waits for it after "checks green" and before the merge, and stops on failure with "migrations did not rehearse on staging's live schema: <reason>". The rehearsal takes about 1 to 3 minutes against roughly 15 minutes of PR CI, so a release takes no longer. `ac-ship` is installed by hand and is not in git; the patch is attached to this card. A follow-up should bring `ac-ship` into the repository.
3. **`.github/workflows/migration-safety.yml`**: the "Require governed schema artifact identity" and "Download only the governed schema bundle" steps go, and the gate runs with `--baseline-from-migrations` (a8216e17, already in wb-ci). That mode applies the same static rules, the released-history check and the full rehearsal. The fictional fixture tests are unchanged. `tests/infra/test_migration_schema_gate.py` will assert that the workflow has no artifact or variable dependency. A `pull_request` workflow runs the PR's own copy of the file, so the v0.87 release PR uses the new check.
4. **Docs**: the AUT-1741 runbook and `docs/ops/WORKBENCH-CI.md` will say that releases no longer need a published staging artifact.

## Why this is the safest option

- **Same tools and the same checks.** The reviewed exporter and gate run unchanged, so the evidence contract is identical. The evidence is minutes old instead of up to 24 hours old.
- **Nothing leaves the server.** No artifact, blob, dispatch, repository variable or pool space is used, and no allowance receipt is needed. The schema dump never leaves ac and is deleted after the run.
- **Trusted evidence.** Root produces it on the server; the PR does not supply it.
- **Read-only on staging.** The export is identical to the one Root runs today.
- **Fail closed.** The release stops before the merge if staging can't be exported or the rehearsal fails.
- **Every PR still rehearses on GitHub.** wb-ci does too, on every commit.

## Risks and trade-offs (CTO decision points)

- **The gate runs as root.** It needs Docker for its disposable PostgreSQL, and acdev has no Docker. So the release commit's migration code runs as root, against a throwaway database only, with no service credentials in its environment. That is the same exposure `ac-ship` already has: it executes the release commit's `native_artifact_compatibility.py` as root. Proposed follow-up: run the candidate's code unprivileged, either with alembic as `nobody` or in a container, with the database as a sidecar.
- **Load on ac.** One disposable PostgreSQL (512 MB cap) and alembic run for 1 to 3 minutes, and only on releases that change migrations. The first run will be measured and posted.
- **Merges outside `ac-ship`.** These lose the live-staging rehearsal until phase 2. In workbench mode, every release goes through `ac-ship`.
- **Staging must be at main's head.** If it isn't, the gate refuses with "schema revision does not cover the PR base migration head". After a normal ship, staging is at main's head, and if it is behind, stopping is correct.

## Phase 2 (separate cards, after two releases on phase 1)

- `ac_release.py deploy staging` refuses a migration-changing core unless a passing receipt exists for that tree. This covers every release path.
- Retire `migration-schema-publish.yml`, the two repository variables and the publication runbook, and close the publication part of AUT-2177, AUT-2214 and AUT-2185.
- Optionally, run the same rehearsal against production's schema before each promotion. That needs the owner's approval, because the exporter is staging-only today.

## Rollout for v0.87

Once the CTO has reviewed it and the CEO has approved:
- Commit items 1, 3 and 4 to the workbench.
- Run wb-ci when the orchestrator opens the window.
- The release owner installs the script as `/usr/local/sbin/ac-schema-rehearsal` from that reviewed commit, along with the `ac-ship` patch.
- Run one rehearsal of the v0.87 candidate against staging, which reads staging and changes nothing, and post its receipt here.
- Then ship v0.87. AUT-2214 no longer blocks it.

If approval does not arrive before the cut, the existing path (AUT-2214) stands unchanged.
