# AUT-1355: native-image prerequisites in pre-ship receipts

The coordinator reported that v0.40.0 passed CI but staging refused it because
`signals.py` changed a native-image input. The fast checker now reports that
prerequisite before staging.

`scripts/ci/ac_fast_check.py` reads `on.push.paths` from the checked commit's
`.github/workflows/sales-xray-native-image.yml`. It records a sorted, deduplicated
top-level `native_inputs_changed` list and prints exactly once when it is nonempty:

```text
needs Root prepare-native before staging
```

The input list is not duplicated in the checker. Exact paths and recursive
directory `/**` patterns cover the workflow's current entries. Missing, malformed
or unsupported input lists make the check unavailable with a bounded diagnostic.
Parsing uses the already installed YAML reader; no dependency or workflow changes
are needed.

Input detection reads the exported committed workflow and an endpoint diff with
rename detection disabled. This preserves removed native inputs and rename sources
and ignores other builders' uncommitted workflow edits. The prerequisite is saved
before check planning, so an unavailable test environment cannot hide it.
It does not change check status, prepare an artifact, or stage a release.

## Validation

The new receipt regression failed before implementation with a missing
`native_inputs_changed` field. All **117 focused checker and committed-snapshot
cases passed in 56.51 seconds**, with no skips or failures. Ruff format/check,
incremental mypy and the required `import ac_platform.http` passed.
Focused validation is recorded in
`/home/acdev/strikes/1355/native-input-validation.json` and
`native-input-tests.xml`. The original 52 checker test functions and assertions
remain unchanged; their preservation receipt is `native-input-test-preservation.json`.

Coverage includes a newly authored workflow path, unrelated inputs, dirty workflow
edits, every current exact path, nested directory inputs, lookalike paths,
deletions, renames, unavailable check planning, and unreadable input lists.
The existing committed-snapshot tests also run because they share the updated
synthetic repository fixture.

## Check a release candidate

Use the previous release's locally available commit as the base, so the comparison
includes every changed native input since that release:

```sh
ac-heavy python scripts/ci/ac_fast_check.py --commit HEAD \
  --base <previous-release-commit> \
  --receipt /home/acdev/strikes/1355/release-preflight.json
```

The coordinator runs Root's `ac-release prepare-native` when the list is nonempty,
then follows the existing release checks. A plan-only receipt confirms selection
and prerequisites; it does not certify those checks or a staging deployment.
