# E4-W1 Calls rep column and loaded-call filter — implementation checkpoint

Task: [AUT-1259](/AUT/issues/AUT-1259).
Source: `858c52f149ac4447211432352c455154f5315e62` (latest main at admission).
Head: `task/sx-org/1259-calls-reps`; the immutable checkpoint SHA is recorded on
AUT-1259 and its branch work product after this evidence file is committed.
Card correction: revision `c241e65e-afb2-40ee-bdcb-63e5de781d7b` permits only full-list
URL fixture changes in `calls-library.test.tsx`; compact previews and all behavior
assertions remain intact.

## Implemented

- Strict optional `owner: {personId, name}` parser output. Missing wire pairs omit
  the property entirely; partial, malformed and unknown fields fail closed.
- Full Calls initial, refresh and pagination reads opt into `include_owners=true`.
  Pagination keeps `before`; previews retain base reads. No server rep filter.
- Desktop rep column and phone Rep label within the existing call-copy area.
  New scoped styles do not alter the phone grid or the reserved Calls stylesheet.
- `Rep (loaded calls)` / `All reps`, UUID selection, unique loaded options and
  numbered same-name labels. Server masked-email fallback is retained as given.
  Rep filtering intersects title search and status before sorting, with Load more
  available when the intersection has no matches.
- Existing identity remount/cancellation clears rep state. Successful metadata
  withdrawal discards prior pages and clears rep, selection, preview and rename
  state. Failed reads retain the last valid scope and existing retry behavior.

All payloads in tests are fictional. There are no backend, migration, owner-screen
contract, other worker file or environment-state changes.

## Commands and results (5 October 2026)

Formatting commands run before the checkpoint:

```sh
pnpm exec prettier --write apps/sales-xray-web/app/acquisition-client.ts apps/sales-xray-web/app/calls-library.tsx apps/sales-xray-web/app/calls-reps.module.css apps/sales-xray-web/app/calls-library.test.tsx
pnpm exec prettier --write apps/sales-xray-web/app/acquisition-library-owners.test.ts apps/sales-xray-web/app/calls-library-reps.test.tsx
pnpm exec prettier --write apps/sales-xray-web/app/calls-library-reps.test.tsx
pnpm exec prettier --write apps/sales-xray-web/app/calls-reps.module.css
```

| Command                                                                                                                                                                                                                                                                                                                          | Checkpoint result                                                                                                                     |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-library.test.ts app/acquisition-library-owners.test.ts app/calls-library.test.tsx app/calls-library-reps.test.tsx app/calls-drawer.test.tsx app/owner-surfaces.test.tsx`                                                                                       | 82 passed, 1 failed, 6 files. All 36 new parser/UI cases pass. The one failure is the excluded exact-URL owner-surface fixture below. |
| `pnpm --filter @ac/sales-xray-web typecheck`                                                                                                                                                                                                                                                                                     | PASS after correcting the new parameterised fixture arrays.                                                                           |
| `pnpm --filter @ac/sales-xray-web exec eslint app/acquisition-client.ts app/calls-library.tsx app/calls-library.test.tsx app/acquisition-library-owners.test.ts app/calls-library-reps.test.tsx --max-warnings 0`                                                                                                                | PASS.                                                                                                                                 |
| `pnpm exec prettier --check apps/sales-xray-web/app/acquisition-client.ts apps/sales-xray-web/app/calls-library.tsx apps/sales-xray-web/app/calls-reps.module.css apps/sales-xray-web/app/calls-library.test.tsx apps/sales-xray-web/app/acquisition-library-owners.test.ts apps/sales-xray-web/app/calls-library-reps.test.tsx` | PASS after correcting CSS formatting.                                                                                                 |
| `uv run ruff format --check packages/python tests`                                                                                                                                                                                                                                                                               | PASS: 1,008 files.                                                                                                                    |
| `uv run ruff check packages/python tests`                                                                                                                                                                                                                                                                                        | PASS.                                                                                                                                 |
| `uv run mypy packages/python`                                                                                                                                                                                                                                                                                                    | PASS: 419 source files.                                                                                                               |
| `uv run pytest tests/unit/conversation_intelligence/test_organisation_call_reads.py tests/unit/http/test_conversation_learner_acquisition.py -q`                                                                                                                                                                                 | PASS: 28 tests.                                                                                                                       |
| `ac-gate check`                                                                                                                                                                                                                                                                                                                  | PASS: task may be worked on.                                                                                                          |
| `git diff --check`                                                                                                                                                                                                                                                                                                               | PASS.                                                                                                                                 |

The first new-test run found three test-fixture failures (Vitest argument expansion
for array cases and an incorrect expected option ordering). Those fixtures were
corrected; the final six-file run passes all new cases. No production behavior was
weakened to satisfy them.

## Exact scope blocker

`apps/sales-xray-web/app/owner-surfaces.test.tsx:94` matches only
`/v1/conversation/acquisition/submissions`. The required full Calls request with
`?include_owners=true` receives its mocked 404, so the owner-surface control test
fails before it can inspect the populated workspace. This file is expressly
excluded by the card. The necessary correction is only that URL fixture; every
owner-approved assertion and `owner-surfaces.json` must stay intact.

Chief of Staff must allow this one fixture correction on the execution card.
The excluded test remains unmodified. No PR is opened with this required check
failing, and no merge or deployed acceptance is claimed.

## Remaining acceptance after scope resolution

Repeat ownership checks for the newly allowed fixture, update only its full-list
URL, rerun the required suite and record bounded local browser layout/focus checks
at 1440px and 390px. Injected fictional UI evidence must be labelled as local.

After governed review/merge, verify the served SHA and existing authorised
fictional owner/admin, member and Personal journeys on dev and the same released
build on staging. No authorised deployed session or serving revision was examined
in this checkpoint; local unit tests are not deployed acceptance. Preserve
AUT-1205's phone-layout repair and browser script throughout.
