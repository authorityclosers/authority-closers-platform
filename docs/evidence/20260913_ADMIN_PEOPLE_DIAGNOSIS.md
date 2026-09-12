# Admin People learner lookup and diagnosis

The People page now resolves an active learner by exact email or canonical public username and displays a redacted diagnosis in the administrator's selected academy. The operator chooses a review purpose, selects the returned learner, and confirms the review before opening course access, pinned version, canonical progress, and draft/evidence metadata.

## Controlled scope

- Admin controlled source: `https://docs.google.com/document/d/12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY/edit`.
- AC-IMP-04: `https://docs.google.com/document/d/1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc/edit`.
- Exact source copies and retrieval metadata are retained in the external release packet's `controlled-support-sources` directory. Earlier required source reads remain in the implementation log.
- This first read boundary covers active people with active, non-ended learner membership in the selected academy. It does not claim a complete directory of inactive people or other roles.
- No correction or enrollment-grant target is enabled by this read. Private draft/evidence payloads, personal profile answers, payments, certificates, analytics, and scoring are outside the response.

## Implementation boundary

`POST /v1/admin/learners/lookup` receives only the exact query and explicit purpose in its body. `GET /v1/admin/learners/{person_id}/diagnosis?purpose=...` diagnoses a selected result. Both use the existing authenticated admin surface and named `learner_diagnose` permission, with server-resolved academy membership. Browser-supplied tenant or permission authority is not accepted. Lookup responses and diagnosis records are strictly validated against the verified client context before rendering.

Every successful lookup, including an empty lookup, and every successful diagnosis appends an audit event with purpose, redaction version, and result count. The lookup key is omitted from the audit payload. The authenticated transaction uses function scope so an audit commit failure prevents private response delivery. Responses use `Cache-Control: no-store`.

Progress comes from the existing canonical catalog resolver, authoritative progress function and projector. Saved drafts and submitted evidence do not independently imply completion. Per-collection limits and truncation indicators prevent a partial view from asserting absence. Missing or inactive access retains enrollment metadata with explicitly unavailable progress.

The UI issues no automatic learner search, requires a purpose without a default, and clears private records when search, purpose, session identity or academy changes. Duplicate in-flight requests are suppressed. A bounded timeout aborts the request and ignores late responses. Authentication/authorization failure removes private results and the search input. The diagnosis heading receives focus on success; activity metadata uses keyboard-operable disclosures and responsive layouts.

## Validation

External evidence directory: `D:\Projects\authority-closers-release-transfer\2026-09-11-recovery\admin-people-validation`.

- Supported Node 24: Admin full suite **689 tests / 31 files passed** before the two additional review regression cases; Admin type checking and scoped lint passed.
- Review follow-up: **49 tests / 3 files passed**, including independent draft/evidence truncation and the live People shell status. Coach shared-package regression suite **40 tests / 3 files passed**, with Coach type checking passed.
- Final Admin type checking passed. Root-scoped ESLint passed for the shared API and changed UI/test files. An earlier app-scoped lint invocation correctly reported that the shared package was outside its base path; the root-scoped rerun covers it.
- Luna xhigh frontend review found two P2 labels: aggregate truncation used for individual metadata streams, and a preview footer on the live People page. Both were fixed with regression assertions.
- Backend validation: **69 unit, HTTP, and app-composition tests passed**, with Ruff clean and mypy passing for both new implementation modules. SQLite query tests cover exact lookup, role/lifecycle/tenant isolation, missing entitlement, and bounded evidence metadata with the latest scoped submission. HTTP tests cover extra/duplicate inputs, audit append failure, and transaction teardown failure without private response leakage.
- Actual PostgreSQL integration: **4 existing admin cases passed**, and the new People case passed after correcting two test-fixture assertions (the redaction version contains the word `learner`, and publication requires an idempotency key). The new case uses canonical publication/grant commands, checks diagnosis and committed read audits, and verifies no activity-progress rows are created. A random test schema is created and dropped by the existing harness. The sandbox migration role correctly denied schema creation; the designated local owner ran the isolated fixture. No database roles were changed.
- The canonical local browser receipt is recorded in the acceptance addendum after execution. This document alone is not browser or deployment acceptance.

## Release boundary

The first real browser attempts exposed two probe/label issues before any diagnosis request: the pre-existing local sign-in button has an implicit submit type, so the probe now locates it by accessible name; the nested purpose label included option text, so the People select now names the visible label explicitly with `aria-labelledby`. The latter has a mounted regression assertion. Failed receipts are retained; they are not acceptance evidence.

The next attempt reached the new lookup and was denied by the development transport's existing exact route allowlist. The follow-up admits only POST lookup without query parameters and GET diagnosis for a UUID with one declared purpose; wrong methods, extra/duplicate query keys, and the Coach surface remain denied. Thirteen transport regression cases cover this boundary. Runtime browser validation keeps the already-started API on the original backend commit while validating that the later frontend-only commits leave all committed backend files unchanged; this avoids loading the separate unfinished email-context work into the API process.

This is a separate follow-on to the recovery release candidate `f0a80f2ca120fb73ce17bb9cdc5b95faf490116d`. It is not included in that frozen deployment candidate. The release owner must integrate the reviewed commit and verify the exact deployed revision before claiming it live. No production database, provider, or deployment changes were made by this UI slice.

## Canonical local browser acceptance

Final receipt: external recovery packet
`canonical-admin-people-20260912T232612Z/proof.json`, passed with frontend
`5c0bb4c73802effcce132e8d9a6a4cfdf8b32e8f` and running API
`c741d0fc413477bece2fabd5e11c3f1fae613368`. The probe verifies every committed
API-to-frontend delta is Admin UI, shared transport/session UI, or evidence.
The running backend was deliberately kept fixed while separate email changes
were uncommitted; this is an explicit composite local proof.

Normal Admin sign-in, explicit exact lookup, purpose/selection/confirmation,
and canonical diagnosis returned the previously saved synthetic draft at
revision 3 and unchanged completion 0 of 5. Read-only PostgreSQL snapshots of
all six learning/enrollment tables remained equal. Both purpose-only access
audits were committed before observation. Normal logout returned 204; the next
read returned 401 and removed learner records, verified header, tenant context
and privileged navigation. Diagnosis focus and keyboard disclosure passed.
No page errors, blocked requests or horizontal overflow at 320/390/1440.
Screenshots were inspected. The query field is intentionally masked.

Earlier successful data-read receipts exposed the stale verified shell during
visual inspection; commit 5c0bb4c fixes it and the final receipt supersedes them.
The development transport correctly adds `private` to `no-store`; the probe
checks the directive as a token rather than requiring one exact header string.

Ordered release source: c741d0f, 93d4281, 4521823, 5c0bb4c. Independent Luna
backend and frontend review, targeted transport/session/Coach regressions,
static checks and the final local browser proof accompany this source. Exact
integrated CI and deployment verification remain release-owner responsibilities.
