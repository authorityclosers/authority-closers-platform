# AUT-2185: recover inventory retries after expiry

The reader now starts each of its five bounded attempts with a fresh timestamp boundary and a count from that attempt's first page. A previous incomplete sweep no longer fixes the expected older count for every later sweep.

## Trigger and provenance

Human source: [24 October report](/AUT/issues/AUT-2185#comment-f90d612e-b41f-4629-822c-e17e68ae02d4). The orchestrator reports old Workbench artifacts expiring during pagination, based on two listings 75 seconds apart, and reports verified upload 12559289440. Those listings and the named laptop side-note are not present in this workspace; the historical causal attribution is not independently certified here.

A read-only GitHub run lookup independently confirms [run 40085655868](https://github.com/authorityclosers/authority-closers-platform/actions/runs/40085655868), source fd2f1cbb36c397388ff289406dd85c125c6fff88, concluded failure at `Reclaim superseded web artifacts after verified upload` (step 11). No logs or customer content were fetched.

## Change

- Refresh the inventory boundary before each fetch and use that sweep's first-page older count. Every successful sweep must account for its current reported rows; an unseen artifact lost before a new sweep is no longer inferred from a previous count.
- Preserve known identities across attempts: unexplained disappearance of an observed older artifact is refused unless the existing expiry rule permits it. Observed older identity/name/size changes still stop immediately. Carry the largest recent sizes, including recent identities absent from a later sweep. Current-sweep missing rows, unseen uploads, hidden boundary and invalid responses still fail closed.
- Five attempts (orchestrator, 24 Oct 2026, for v0.88), 30 s then 60 s apart (at most four minutes of waiting), so an expiry burst can finish between sweeps; the 120 s fetch timeout, no partial stdout, page-size/schema checks, expiry margin, storage bounds, full candidate reserve, verification-before-reclaim and cross-workflow serialization. Continuous expiry can still exhaust all five attempts; this is not permission to accept incomplete pagination or to retry indefinitely.
- Set `DOCKER_BUILD_RECORD_UPLOAD: "false"` in the three image-building workflows, covering all six existing pinned Docker build steps. [Official Docker action documentation](https://github.com/docker/build-push-action#environment-variables) defines this switch. It changes future automatic build-record uploads only; image outputs and verified release artifacts remain governed by their existing steps.
- Reduce application `python-test-shard-*` retention from 14 days to 1 day. Existing Workbench shard retention is already 1 day and is unchanged. The other 14-day browser/root diagnostic uploads are unchanged. No existing artifact was deleted or modified.

## Deterministic reproduction

The evidence uses fictional 201-row metadata. ID 101 disappears before page 2 observes it: page 1 reports 201, page 2 reports 200. The next sweep is complete at 200 rows. On the original reader, all three attempts reject with `older artifact count changed during inventory`. On the candidate, the first attempt rejects; the second complete sweep returns 200 artifacts / 2,000 bytes. Both versions publish no partial stdout. No network call is used in this reproduction.

The focused tests also assert the refreshed time boundary, rejection of a known nonexpiring loss, cross-attempt old-size checks, largest recent-byte charging, expiry reconciliation, concurrent upload completeness, bounded retry exhaustion, one-day shard policy and all six effective Docker settings.

## Validation

`uv run pytest -q tests/infra/test_artifact_inventory.py tests/infra/test_release_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_migration_schema_publication.py tests/infra/test_workbench_artifact_retention.py`

225 passed, 1 skipped, 44.29 seconds. The skip is the existing real PostgreSQL transport proof, exercised by migration-safety CI. Ruff lint/format, Prettier for the three workflows, required `uv run python -c "import ac_platform.http"`, and diff whitespace checks pass.

## Source and review handoff

Initial workbench source 8fd24351268dee9391406d807dd6503f9ad12b52. The attached source manifest and patch pin the tested implementation; baseline-reproduction.json records its exact original source. Other builders' unfinished files are preserved.

The repository's current WORKBENCH order forbids builder branches and PR creation. This change is committed only through `wb-commit` and submitted to the CTO as a sensitive infra/workflow source review. The authorized release operator owns any release PR, hosted CI and deployment. No live inventory/admission sweep, artifact deletion, settings/pool/pointer change, schema export/publication, CI dispatch, host install or release was performed. Earlier successful schema admission handoffs remain completed evidence and are not replayed.

## Follow-up (Align 3, 24 Oct 2026)

Attempts raised from 3 to 5, with sleeps of `min(60, 30 * attempt)` seconds (30, 60, 60, 60) instead of 2 and 4. Tests pinned to the old count, messages and sleeps were updated, and the fakes that exhaust the retries now give five responses. `uv run pytest -q tests/infra/test_artifact_inventory.py tests/infra/test_release_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_migration_schema_publication.py tests/infra/test_workbench_artifact_retention.py`: 225 passed, 1 skipped (with `gh` on PATH, which the reclaim tests require).
