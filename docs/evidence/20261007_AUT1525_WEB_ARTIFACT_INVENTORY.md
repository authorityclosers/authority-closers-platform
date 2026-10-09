# AUT-1525: bounded, complete web artifact inventory reads

Source base: current main `99e8934ed530a67f90dd7dac76888580de57fbf9`.
`ac-gate status` reported devenv FREE and main running; `ac-gate start devenv
1525-artifact-inventory-recovery` claimed the branch and `ac-gate check` passed.
The checkout was clean before edits. `git merge-base --is-ancestor
422ec362af6e0fc867fa0053bb2f5c89e78fe656 HEAD` exited 0.

## Incident boundary

[Web run 37642277703, attempt 1](https://github.com/authorityclosers/authority-closers-platform/actions/runs/37642277703)
uploaded the Calls descendant artifact but failed its cleanup step with
`unexpected end of JSON input`. Its historical request, page, HTTP status and
runner CLI version remain unproved. This repair addresses incomplete transport
and JSON evidence; the incident does not establish a pool-capacity failure.
The earlier pool arithmetic and reclamation policy remain in force.

## Minimal file scope

- `.github/workflows/sales-xray-web-image.yml`: replace its two inventory
  functions (three call sites); include the helper in the push path filter.
- `infra/release/read-artifact-inventory.py`: read-only transport and validation.
- `tests/infra/test_sales_xray_web_artifact_pool.py`: reader and workflow regressions.
- `tests/infra/test_reclaim_artifact_pool.py`: necessary fixture correction only;
  add the API's expiry field and a correctly sized page with `total_count`.
  Its previous response omitted count metadata and emitted two short pages.
  The strict reader exposed two failures in this existing admission regression.
- This implementation-evidence document.

The additional fixture file is required to preserve the existing real-workflow
reclamation regression while enforcing the API contract. No other workflow,
selector, application, host or deployment code changes.

## Reader behavior

Each attempt invokes `gh api --paginate --slurp` from page one with the existing
Accept and API-version headers. Three attempts each have a 120-second subprocess
timeout, with 2- and 4-second retry delays: 366 seconds of CLI/wait budget per
read. No failed attempt's pages reach stdout or a later attempt's inventory.
Captured CLI stderr and response bodies are never printed as diagnostics.
Operation, attempt, exit/timeout or validation category, and successful page,
artifact and byte counts go to stderr.

The reader requires a nonempty outer page list, valid JSON without duplicate
object keys, integer nonnegative `total_count` on every page, stable counts,
exact page lengths for `per_page=100`, the expected number of pages, and a
matching flattened count. Artifacts must have unique positive integer IDs,
nonnegative integer sizes (booleans and strings fail), nonempty string names
and boolean expiry flags. Only one explicit zero-count page proves an empty
inventory. A count change, duplicate, missing page or malformed record fails
closed and restarts the entire read.

These checks follow the [GitHub artifact API](https://docs.github.com/en/rest/actions/artifacts?apiVersion=2026-03-10#list-artifacts-for-a-repository)
and the [CLI pagination/slurp contract](https://cli.github.com/manual/gh_api).
Count validation detects incomplete pagination and common inventory movement;
the API does not provide a transactional snapshot. A repeatedly changing pool
can exhaust the bounded reads rather than permit cleanup from incomplete data.

Admission consumes only a validated inventory. After the existing five-attempt
upload identity proof, cleanup consumes another validated inventory; a failed
read exits before any DELETE. The final read also fails closed: cleanup already
authorized by complete earlier evidence is not undone, but the step cannot
assert successful final pool verification from incomplete evidence.

## Preserved policy and local verification

The current upload ID/run/name/expiry/positive-size proof, exact lowercase web
bundle matching, current-ID exclusion, Application/native/unrelated protections,
pooled arithmetic, existing reclamation helper, serialized packaging, one-day
retention and image/artifact ceilings are unchanged. No continue-on-error or
workflow-success admission exception was added. A parsed YAML comparison with
the source base confirmed that only inventory calls and the helper path trigger
changed; the remaining steps, metadata and job settings are identical.

```sh
uv run --frozen pytest tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_release_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py tests/infra/test_recovery_ci_gates.py -q
uv run --frozen ruff check infra/release/read-artifact-inventory.py tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py
uv run --frozen ruff format --check infra/release/read-artifact-inventory.py tests/infra/test_sales_xray_web_artifact_pool.py tests/infra/test_reclaim_artifact_pool.py
pnpm exec prettier --check .github/workflows/sales-xray-web-image.yml docs/evidence/20261007_AUT1525_WEB_ARTIFACT_INVENTORY.md
git diff --check
```

**110 tests passed**. Ruff lint/format checks passed. Workflow and evidence
formatting and the diff whitespace check passed.

Regression coverage includes multi-page success, nonzero gh with valid partial
stdout, empty/truncated JSON despite gh exit 0, missing pages, invalid schema,
IDs and sizes, transient recovery, exhausted retries, duplicate identities,
count drift and timeout. Workflow checks prove no deletion or admission from
failed precleanup evidence, no successful final assertion from a failed final
read, current/unrelated protection and the exact 2,000,000,000-byte configured
pool boundary and individual ceilings.

## Live read-only receipt

At **2026-10-07 17:21:28 UTC**, the helper completed on attempt 1: **82 pages,
8,196 artifacts, 1,979,452,444 bytes**. This is current inventory, not historical
cause evidence or an operator deletion list. Artifact **11491809592** remained
present and unexpired:

- Name: `ac-sales-xray-web-422ec362af6e0fc867fa0053bb2f5c89e78fe656`.
- Size: `94,362,808` bytes.
- Digest: `sha256:9b4e1fb78ba38b7c7ff4a21b7064b9fa97bde53214ef24e9eda0b1ca0c83e401`.

No operator artifact deletion, rerun, original-image rebuild, manual publishing,
settings change, deploy or production action occurred.

## Required release receipt before completion

CTO review and CEO SHA-bound approval precede watchdog merge. The repair must
then produce an ordinary main-push descendant of `422ec36` with successful
same-SHA Application validation and Sales Xray web-image workflows. Automatic
staging must serve that descendant with matching edge `/health` release ID and
a healthy immutable image. These post-merge receipts are pending; PR validation
and this read-only inventory probe do not establish deployed recovery.

Root retains independent staging verification on AUT-1523. Watchdog CI/head
events own continuation; no CI polling timer is created. Public 403 and
authenticated fictional visual/journey checks remain unverified and advisory.
