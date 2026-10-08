# E4-W1 Calls rep column and loaded-call filter — implementation evidence

Task: [AUT-1259](/AUT/issues/AUT-1259).
Admission source: `858c52f149ac4447211432352c455154f5315e62`.
Preserved implementation checkpoint: `20b266d218e23eb3a7c3609de47e1780b8e77e78`.
Branch: `task/sx-org/1259-calls-reps`; final head is recorded on the PR and task
work product. The browser receipt records SHA-256 digests of the rendered files.

Card revision 4 (`c6187c4c-3ba0-4773-abc7-4e2110a95a3e`) saves the answered
fixture exceptions: full-list URLs in `calls-library.test.tsx` and only the full
Calls URL in `owner-surfaces.test.tsx`. Every behavior assertion, compact preview
request and `owner-surfaces.json` is preserved.

## Implemented

- Strict optional `owner: {personId, name}` parser output. Missing wire pairs omit
  the property entirely; partial, malformed and unknown fields fail closed.
- Full Calls initial, refresh and pagination reads opt into `include_owners=true`.
  Pagination keeps `before`; previews retain base reads. No server rep filter.
- Desktop rep column and phone Rep label within the existing call-copy area.
  Scoped styles preserve the existing duration/status layout and reserved grid.
  The rep control occupies its own phone row so the search field retains space.
- `Rep (loaded calls)` / `All reps`, UUID selection, unique loaded options and
  numbered same-name labels. Server masked-email fallback is retained as given.
  Rep filtering intersects title search and status before sorting, with Load more
  available when the intersection has no matches.
- Identity remount/cancellation clears rep state. Successful metadata withdrawal
  discards prior pages and clears rep, selection, preview and rename state. Failed
  reads retain the last valid scope and existing retry behavior.
- The authorised owner-surface request-fixture URL now includes the required flag;
  none of its assertions changed.

Production diff is 221 changed lines across parser, component and scoped CSS,
within the card's limit. All payloads are fictional. No backend, migration, secret,
provider, owner-screen contract or environment-state change is included.

## Checks on 5 October 2026

`ac-gate status` identified this same task as free to continue; main was running
(new work allowed; merges await green). `ac-gate check` passed before continuation.
The sx-org checkout was clean at resumption. Read-only status checks of all lane
checkouts and files in open PRs #342, #336 and #331 found no allowed-file overlap,
including the newly allowed `owner-surfaces.test.tsx` fixture. Other lane changes
and [AUT-1205](/AUT/issues/AUT-1205)'s stylesheet/browser script were untouched.

Prior checkpoint: 82 passed / 1 failed because the then-excluded owner-surface URL
fixture returned 404. The answer resolved that failure. In this run the required
parallel suite had 81 passes and two existing tests exceeded their unchanged
5-second timeout (duplicate-page guard and owner report sections). A bounded
single-worker rerun passed all 83 tests without changing tests, timeouts or behavior.
All 36 new parser/UI cases pass.

Formatting commands run before saving changed web files in this continuation:

```sh
pnpm exec prettier --write apps/sales-xray-web/app/owner-surfaces.test.tsx
pnpm exec prettier --write apps/sales-xray-web/app/calls-reps.module.css
```

| Exact command                                                                                                                                                                                                                                                                                                                                                                    | Result                                                                                                               |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-library.test.ts app/acquisition-library-owners.test.ts app/calls-library.test.tsx app/calls-library-reps.test.tsx app/calls-drawer.test.tsx app/owner-surfaces.test.tsx`                                                                                                                                       | 81 passed; 2 existing tests timed out at 5 seconds during concurrent checks. The corrected Calls URL fixture passes. |
| `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-library.test.ts app/acquisition-library-owners.test.ts app/calls-library.test.tsx app/calls-library-reps.test.tsx app/calls-drawer.test.tsx app/owner-surfaces.test.tsx --no-file-parallelism --maxWorkers=1`                                                                                                  | PASS: 6 files, 83 tests, 53.48 seconds.                                                                              |
| `pnpm --filter @ac/sales-xray-web typecheck`                                                                                                                                                                                                                                                                                                                                     | PASS.                                                                                                                |
| `pnpm --filter @ac/sales-xray-web exec eslint app/acquisition-client.ts app/calls-library.tsx app/calls-library.test.tsx app/acquisition-library-owners.test.ts app/calls-library-reps.test.tsx app/owner-surfaces.test.tsx --max-warnings 0`                                                                                                                                    | PASS.                                                                                                                |
| `pnpm exec prettier --check apps/sales-xray-web/app/acquisition-client.ts apps/sales-xray-web/app/calls-library.tsx apps/sales-xray-web/app/calls-reps.module.css apps/sales-xray-web/app/calls-library.test.tsx apps/sales-xray-web/app/acquisition-library-owners.test.ts apps/sales-xray-web/app/calls-library-reps.test.tsx apps/sales-xray-web/app/owner-surfaces.test.tsx` | PASS, including the final phone control styles.                                                                      |
| `uv run ruff format --check packages/python tests`                                                                                                                                                                                                                                                                                                                               | PASS: 1,008 files.                                                                                                   |
| `uv run ruff check packages/python tests`                                                                                                                                                                                                                                                                                                                                        | PASS.                                                                                                                |
| `uv run mypy packages/python`                                                                                                                                                                                                                                                                                                                                                    | PASS: 419 files.                                                                                                     |
| `uv run pytest tests/unit/conversation_intelligence/test_organisation_call_reads.py tests/unit/http/test_conversation_learner_acquisition.py -q`                                                                                                                                                                                                                                 | PASS: 28 tests.                                                                                                      |
| `ac-gate check`                                                                                                                                                                                                                                                                                                                                                                  | PASS for this task.                                                                                                  |
| `git diff --check`                                                                                                                                                                                                                                                                                                                                                               | PASS.                                                                                                                |

## Bounded local browser evidence and retained acceptance gap

The [uploaded fixture bundle](/api/attachments/59000f5b-2622-4f6a-ab2e-1ae92643e6b8/content) contains `calls-reps-browser.mjs`, receipts and
sanitised screenshots. It renders the actual CallsLibrary and repository styles,
including local font assets, in fresh Chromium contexts at 1440px and 390px. Vite
builds the fixture in memory; browser routes supply the page. Navigation, outer
shell and report insights are mocked. All rows are fictional; no deployed session,
server state, provider, real call or credentials are used. This is **local injected
component evidence**, not dev/staging acceptance.

Exact commands (script is in the issue artifact bundle):

```sh
node "$PAPERCLIP_RUN_SCRATCH_DIR/calls-reps-browser.mjs"
AC_CALLS_REPS_BASELINE=1 node "$PAPERCLIP_RUN_SCRATCH_DIR/calls-reps-browser.mjs"
```

- 1440px: rep, duration and status are visible without overlap; UUID selection
  filters to the correct same-name rep. The combobox's exact accessible name is
  `Rep (loaded calls)`, and keyboard focus has a solid 2px outline.
- 390px: rep label, UUID filter, keyboard focus and horizontal bounds pass. The
  added control's own phone row retains the search field. Duration/status overlap
  and insufficient duration-slot width remain **failed** acceptance checks.
- The second command loads CallsLibrary directly from pinned main using `git show`
  and base rows without owner fields. It reproduces the same two 390px failures:
  duration slot width 25px, clock width about 86.23px, clock x=135..221.23 and status
  x=162..257. Both runs deliberately exit 1 and record these failures. Desktop
  baseline is clear. This local comparison establishes that the phone defect is
  already present without this rep change.
- [AUT-1205](/AUT/issues/AUT-1205) owns that exact phone-duration repair. Its
  `calls-library.module.css` and browser script remain excluded. Final phone
  acceptance needs its corrected layout output; do not widen this PR to repair it.

## Existing API consumed

`GET /v1/conversation/acquisition/submissions?include_owners=true`

Next page retains the flag and adds `&before=<submission UUID>`. The shape remains
`{submissions: SavedCall[], next_cursor: UUID | null}`; selected-organisation
owner/admin rows may add the complete `owner_person_id` / `owner_name` pair.
Member/Personal base rows omit it. No endpoint or permission change is introduced.

```json
{
  "submissions": [
    {
      "submission_id": "11111111-1111-4111-8111-111111111111",
      "created_at": "2026-10-04T09:00:00+00:00",
      "duration_seconds": 90,
      "display_name": "Fictional discovery call",
      "display_name_revision": 1,
      "state": "report_ready",
      "has_report": true,
      "owner_person_id": "22222222-2222-4222-8222-222222222222",
      "owner_name": "Fictional Rep"
    }
  ],
  "next_cursor": null
}
```

## Governed handoff and deployed checks

Another eligible Sol pod lead reviews this PR. CEO merge approval follows. The
final browser acceptance stage remains open through governed merge and verified
dev/staging visibility; review or approval alone must not complete the delivery.
CI completion and changed-head checks use the existing watchdog event path, with
no polling timer or merge/deployment action in this run.

After merge, record the served SHA and check the existing authorised fictional
owner/admin session at both widths: two reps, UUID filter plus status/search,
next-page rep options and the same report navigation. Then switch to the existing
fictional member and Personal: no rep controls or another member's calls. Refresh
and switch workspace to verify state reset. Repeat on the same build in staging.
No authorised deployed session or serving revision was examined in this run.
If those inputs are unavailable, record the exact gap and reuse its concrete
existing operator/release task. The separate handle/profile runtime receipt is
not a build prerequisite.

## Round-one review correction (5 October 2026)

Reviewed head: `ee1a1a341181fad2d7b6a307de938e258713064f`.
Card revision 6 (`dd634abb-ce58-440e-b3c7-817fcdfb0ef5`) records the pod lead's
bounded learner URL-fixture exception. The clean sx-org checkout, current gate
and read-only statuses across lane checkouts permit continuation. Open PR #346
has no overlapping files, including the newly allowed learner test.

The learner journey mock now accepts the explicit full-list suffix
`/submissions?include_owners=true` as well as its existing `/submissions` suffix.
All assertions, compact-preview requests and production files are unchanged by
this correction. No timeouts or test behavior checks were weakened.

Before the change, the isolated reviewed case reproduced the CI failure at
line 423: the rejected list read prevented `Report ready` from rendering.
After the change, the full learner journey suite passes all 10 cases, including
report navigation and the assertion that no processing mutations occur.

| Exact command | Result |
| --- | --- |
| `pnpm --filter @ac/learner-web exec vitest run app/sales-xray/acquisition-journey.test.tsx -t 'opens an account library result in the learner report route without processing it' --no-file-parallelism --maxWorkers=1` | Expected pre-fix failure: 1 failed, 9 skipped; same line 423 assertion as CI. |
| `pnpm exec prettier --write apps/learner-web/app/sales-xray/acquisition-journey.test.tsx` | PASS; no further formatting edits. |
| `pnpm --filter @ac/learner-web exec vitest run app/sales-xray/acquisition-journey.test.tsx --no-file-parallelism --maxWorkers=1` | PASS: 1 file, 10 tests. |
| `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-library.test.ts app/acquisition-library-owners.test.ts app/calls-library.test.tsx app/calls-library-reps.test.tsx app/calls-drawer.test.tsx app/owner-surfaces.test.tsx --no-file-parallelism --maxWorkers=1` | PASS: 6 files, 83 tests. Uses the previously verified single-worker setting; no timeout changes. |
| `pnpm --filter @ac/sales-xray-web typecheck` | PASS. |
| `pnpm --filter @ac/learner-web exec eslint app/sales-xray/acquisition-journey.test.tsx --max-warnings 0` | PASS. |
| `pnpm --filter @ac/sales-xray-web exec eslint app/acquisition-client.ts app/calls-library.tsx app/calls-library.test.tsx app/acquisition-library-owners.test.ts app/calls-library-reps.test.tsx app/owner-surfaces.test.tsx --max-warnings 0` | PASS. |
| `pnpm exec prettier --check apps/sales-xray-web/app/acquisition-client.ts apps/sales-xray-web/app/calls-library.tsx apps/sales-xray-web/app/calls-reps.module.css apps/sales-xray-web/app/calls-library.test.tsx apps/sales-xray-web/app/acquisition-library-owners.test.ts apps/sales-xray-web/app/calls-library-reps.test.tsx apps/sales-xray-web/app/owner-surfaces.test.tsx apps/learner-web/app/sales-xray/acquisition-journey.test.tsx` | PASS. |
| `uv run ruff format --check packages/python tests` | PASS: 1,008 files. |
| `uv run ruff check packages/python tests` | PASS. |
| `uv run mypy packages/python` | PASS: 419 source files. |
| `uv run pytest tests/unit/conversation_intelligence/test_organisation_call_reads.py tests/unit/http/test_conversation_learner_acquisition.py -q` | PASS: 28 tests. |
| `ac-gate check` | PASS: this existing task may be worked on. |
| `git diff --check` | PASS. |

The earlier local browser receipts remain valid for the unchanged production
files. Their documented 390px duration/status gap still belongs to
[AUT-1205](/AUT/issues/AUT-1205). Final browser acceptance on dev and staging
remains open after governed merge. This test-fixture correction introduces no
new browser or deployed-acceptance claim; frontend CI is checked for the pushed
head through the existing watchdog event path.
