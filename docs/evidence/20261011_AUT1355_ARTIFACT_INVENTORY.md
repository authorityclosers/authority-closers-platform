# AUT-1355: concurrent artifact inventory repair

Source pin: `abbebddf5634c58303ebcc13d3b03713078ab338` (gate-fetched main).

The 11 October inbox reports red main at `bcd4e40`: concurrent PR uploads shift
artifact pages, causing both inventory readers to reject changed counts or
repeated IDs before release admission can prove the repository pool size.

Admission and reclamation now share a bounded, three-attempt reader. It fixes
the snapshot time before the first request, deduplicates artifact IDs, and
checks the number and sizes of artifacts predating that boundary. The boundary,
original count and observed older identities survive retries; retries cannot
silently accept a smaller pool after an older artifact disappears. Missing
pages, malformed metadata and transport failures still fail closed. Older
identity/size changes fail immediately. Each accepted sweep also accounts for
the largest repository artifact count reported by its pages. A sweep covering
all older identities but omitting new uploads retries from page one; sustained
unobserved uploads exhaust the existing three attempts without publishing a
partial inventory. Recent observations survive retries, charging the largest
observed size per ID even when a later sweep omits that recent ID.

GitHub timestamps have second precision. The proof excludes the start second
from its older set, while charging observed bytes, so an upload started during
that second can finish without being misclassified as an older size change.

The GitHub API exposes page, page size and name filters, with no snapshot-time
filter. Repository admission needs all artifact sizes, so filtering by release
artifact name would undercount. The snapshot proof uses the observed newest-first
listing; it refuses to guess when a complete first page of post-boundary uploads
hides the boundary. API reference:
<https://docs.github.com/en/rest/actions/artifacts>.

Per the 11 October shared-file order, this repair leaves application.yml exactly
as on main. The diagnostic retention reduction (fourteen to two days) is saved
for a separate small follow-up after PRs #442 and #437 merge. Visual evidence
and release artifact retention remain unchanged. This inventory repair does
not delete existing diagnostic artifacts or relax the ceiling.

Validation on the AC server after CTO review at `9af6cce`:

- Before the fix, the real workflow's admission step accepted the 201 -> 202 ->
  203 fixture at a projected **1,405,000,000 bytes**, omitting two 500 MB uploads.
  After the fix it rejects that incomplete sweep, recovers all 203 artifacts
  on attempt two, and refuses the **2,405,000,000-byte** projection against the
  unchanged 2 GB ceiling. The fixture invokes the repository workflow and shared
  readers with synthetic CLI responses; it verifies no deletion occurred.
- Before the fix, a retry observing recent ID 101 at 500 bytes and then 1 byte
  returned **1,001 bytes**. Afterward it retains the **1,500-byte** bound. A
  second case verifies the bound survives when the recent ID disappears from
  the subsequent sweep. Repeated unobserved uploads fail after three attempts.
- `ac-heavy uv run --offline --frozen pytest tests/infra/test_artifact_inventory.py tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py tests/infra/test_release_artifact_pool.py -q -x`: **122 passed in 17.79 s**.
  Every original test function remains; four cases were added. Fixtures that
  previously accepted an unbounded upload gap now require its recovery or
  rejection, preserving older-byte, second-precision and size-bound assertions.
- Focused Ruff/format checks, incremental mypy on both readers and
  `git diff --check`: passed. No workflow, dependency or gate file changed.
- Raw before/after receipts are in the strike folder:
  `review-unseen-uploads-before-valid.xml`, `review-recent-size-before.xml`, and
  `review-admission-after.xml`. The earlier `review-unseen-uploads-before.xml`
  used an out-of-range pool fixture and is not evidence of the admission defect.

Historical validation before those review corrections:

- `ac-heavy uv run --offline --frozen pytest tests/infra/test_artifact_inventory.py tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py tests/infra/test_release_artifact_pool.py -q -x`: **118 passed in 21.79 s**.
- Focused Ruff/format checks, incremental mypy on both readers (`--follow-imports=silent`) and `git diff --check`: passed. The dynamic shared-reader return has an explicit type annotation; runtime inventory behavior is unchanged.
- Retention deferral: the new inventory policy test retains fourteen diagnostic days until the ordered follow-up. All 29 inventory/workflow/retention cases passed in 2.07 s, Ruff and Prettier passed, and application.yml is byte-for-byte identical to fetched main. No test was removed; the PR has no shared-file diff.
- Read-only live admission inventory: **attempt 1/3**, **92 pages**, **9,154
  unique artifacts**, **2,244,516,417 bytes**. No artifact deletion was invoked.
- Open PR file inventory: no overlap with the six implementation/test files.

That historical snapshot was above the inbox's 2 GB ceiling. Release admission must
continue to refuse if existing permitted superseded-artifact reclamation cannot
make room. GitHub CI and CTO/CEO review remain required for this sensitive
workflow/infrastructure repair. No deployment, manual merge, or production/data
change was performed.
