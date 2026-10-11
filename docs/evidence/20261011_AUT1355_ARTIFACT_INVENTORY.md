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
identity/size changes fail immediately. New uploads do not invalidate the older
snapshot, and any observed new bytes still count conservatively (the largest
observed size for a repeated new ID).

The GitHub API exposes page, page size and name filters, with no snapshot-time
filter. Repository admission needs all artifact sizes, so filtering by release
artifact name would undercount. The snapshot proof uses the observed newest-first
listing; it refuses to guess when a complete first page of post-boundary uploads
hides the boundary. API reference:
<https://docs.github.com/en/rest/actions/artifacts>.

Diagnostic Python-shard, acquisition-browser and hosted-activation receipts
retain for two days instead of fourteen. Visual evidence already retains for
one day. Release artifact retention and reclamation eligibility are unchanged.
Retention applies to future uploads; this change does not delete existing
diagnostic artifacts or relax the ceiling.

Validation on the AC server:

- `ac-heavy uv run --offline --frozen pytest tests/infra/test_artifact_inventory.py tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py tests/infra/test_release_artifact_pool.py -q -x`: **117 passed in 19.79 s**.
- Focused Ruff checks and `git diff --check`: passed.
- Read-only live admission inventory: **attempt 1/3**, **92 pages**, **9,154
  unique artifacts**, **2,244,516,417 bytes**. No artifact deletion was invoked.
- Open PR file inventory: no overlap with the six implementation/test files.

The live pool is still above the inbox's 2 GB ceiling. Release admission must
continue to refuse if existing permitted superseded-artifact reclamation cannot
make room. GitHub CI and CTO/CEO review remain required for this sensitive
workflow/infrastructure repair. No deployment, manual merge, or production/data
change was performed.
