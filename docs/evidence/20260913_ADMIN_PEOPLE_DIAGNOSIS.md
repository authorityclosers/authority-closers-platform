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

This is a separate follow-on to the recovery release candidate `f0a80f2ca120fb73ce17bb9cdc5b95faf490116d`. It is not included in that frozen deployment candidate. The release owner must integrate the reviewed commit and verify the exact deployed revision before claiming it live. No production database, provider, or deployment changes were made by this UI slice.
