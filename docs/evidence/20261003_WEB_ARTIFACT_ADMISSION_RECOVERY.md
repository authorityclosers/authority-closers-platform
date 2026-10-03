# Web artifact admission recovery

Task: [AUT-1072](/AUT/issues/AUT-1072), implementing the finding in
[AUT-1036](/AUT/issues/AUT-1036) for [AUT-1032](/AUT/issues/AUT-1032).
Base: `22bbede4806499ef4487268e6ff2273b546e7ca8`.
Required ancestor: `28922fc609c86fc97de54ad46877d821f5e89fba` (PR #255).

## Failure and bounded implementation

The diagnosis in [AUT-1071](/AUT/issues/AUT-1071) reports a projected repository
artifact pool of 2,038,604,755 bytes against its configured 2,000,000,000-byte
ceiling. Web packaging counted superseded web bundles without replacing them.
The supplied Root receipt says the staging companion still serves
`c387b2d12be65c03342c19dce2390b112bee8b8f`. These are assignment receipts;
this implementation run did not inspect or mutate the host.

Implementation choice: apply the existing Application packaging lifecycle to
the web bundle family. Admission subtracts only artifacts named exactly
`ac-sales-xray-web-<40 lowercase hexadecimal characters>` from repository usage
before adding the candidate. All Application, native, evidence and malformed
web names remain counted. The pool variable, validator, default, configured
2 GB allowance and 450 MB candidate limit are unchanged.

The existing pinned upload action retains the replacement for one day. Cleanup
starts only after the API proves the uploaded artifact's ID, frozen-source
name, current workflow run ID, unexpired status and positive size. It removes
only matching web bundles other than that exact upload ID, including an older
run's same-source bundle. It then reads the inventory again and requires the
replacement to remain present and total usage to meet the configured ceiling.
An inventory, upload-proof or deletion failure fails the job.

As in Application packaging, admission describes the pool after verified
cleanup; old and new bundles temporarily coexist during upload. A failed
replacement proof preserves the old bundles. No artifact is deleted by this
local implementation run. The existing shared packaging concurrency group
serializes uploads and reclamation. Only this packaging job gains
`actions: write`; top-level permissions remain read-only.

Source changes are limited to the web image workflow, its focused regression
test file and this evidence document. Image identity, frozen source, transport
checksums, release marker, health proof, release engine and staging selection
contracts remain unchanged.

## Local verification

Executed on 2026-10-03 with synthetic metadata and local executable fixtures.
The tests parse the committed workflow and execute its actual admission and
cleanup shell bodies; their GitHub fixture returns paginated inventory and
records deletion calls. They do not connect to GitHub, a database or a provider.

```sh
uv run --no-sync pytest \
  tests/infra/test_release_artifact_pool.py \
  tests/infra/test_sales_xray_web_artifact_pool.py \
  tests/unit/releases/test_sales_xray_web_artifact.py -q
uv run --no-sync ruff check tests/infra/test_sales_xray_web_artifact_pool.py
uv run --no-sync ruff format --check tests/infra/test_sales_xray_web_artifact_pool.py
git diff --check
```

Result: **37 passed** in 7.62 seconds. Ruff lint and formatting passed. All six
workflow shell steps passed `bash -n`; workflow YAML parses successfully.
Latest-main gate status was green with devenv free; start claimed
`task/devenv/1072-web-artifact-admission`, and `ac-gate check` passed.

The regression fixture reproduces the reported 2,038,604,755-byte projection
with a synthetic 400 MB superseded bundle and 400 MB candidate. The repaired
projection is 1,638,604,755 bytes. Other cases cover exact-ceiling acceptance,
one-byte-over refusal, the candidate's independent ceiling, preservation of the
current upload and other artifact families, mismatched/missing/expired/empty
upload proof, inventory failure, deletion failure and final-pool refusal.
These arithmetic results are local fixtures, not a new live storage receipt.

## Dev and staging completion checks

This workflow change triggers the normal main-push web image build after the
PR merges. Application validation also runs on that exact main SHA. The
installed selector requires successful **main-push** Application validation at
the image candidate's source SHA; a manual dispatch does not satisfy it.

After sensitive CTO review and CEO exact-SHA approval, the watchdog owns the
merge. Use its completion events rather than CI polling or a SHA-only rebuild.
Record the following on the task before declaring completion:

1. Exact merged main SHA and ancestry containing PR #255's merge.
2. Successful main-push Sales Xray web image run, uploaded bundle ID and final
   pool receipt at that SHA.
3. Successful main-push Application validation run at the same SHA.
4. Existing automatic staging tick selection of that immutable candidate.
5. Root's independent served source and health verification on
   [AUT-1032](/AUT/issues/AUT-1032), covering dev and staging. Lead retains
   [AUT-1016](/AUT/issues/AUT-1016) reconciliation.

The merged SHA, automatic build/validation receipts and deployed recovery are
pending review and merge at the time of this local evidence. This document
does not claim deployment success. Revert through a reviewed source change if
needed; never delete artifacts manually, edit installed files, restart services
or bypass a hold to recover.
