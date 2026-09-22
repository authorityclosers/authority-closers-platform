# Sales Xray reliability repair — implementation evidence

Base: `1a16a4b8defe0f4c36cc4bda5b72ada02c005b17`.
Candidate branch: `codex/sales-xray-reliable-20260922`.
Status: candidate `9986cf2e` passed exact-source CI and is deployed to staging;
live testing found a frontend contract mismatch corrected by this follow-up.
Production and final browser acceptance remain pending.

## Authority and scope

The founder authorized implementation of the September 22 recovery audit and repeated verification through the deployed guest/account journey. Required controlled Drive documents were retrieved by exact manifest IDs before edits. Additional context: Software Intelligence Control Register, spreadsheet `1S6Bq2Kppq0Wzisq9tgKwiISU7U4RUVLRd7Fg6VOy5WY`, bounded BUGS_RISKS/START/TEST_MATRIX/RELEASES reads and exact linked evidence for RISK-11/12/13/15. These findings were checked against source; the sheet does not replace controlled policy.

No official numerical scoring, provider allowance expansion, direct operational SQL repair, or privacy/retention bypass is part of this change. Report output remains an evidence-bound advisory draft.

## Report and retained-response changes

- Resolve scalar finding detail evidence using explicit finding_index, rejecting malformed/duplicate/out-of-range indices rather than relying on array position.
- Normalize the declared flattened overview before scalar adaptation. Optional business impact stays optional; missing required overview fields fail validation instead of silently downgrading to a legacy report.
- Compose existing single-span evidence and scalar diagnosis adapters without weakening quote/time/source validation.
- Bind retained C5 deduplication and proof to source-owned validator revision. Preserve command intent so an original idempotency key returns its original result after an upgrade. A new command uses the current validator and appends a new version if needed. Existing run locking serializes concurrent requests.

## Measured local verification

- Report/overview/structure/retained recovery unit suites: **133 passed**.
- PostgreSQL 18.6 migration and retained response suites: **3 passed**, including a historical unversioned negative receipt, exact old-key replay, two concurrent new-key revalidations creating one new version, zero provider calls, and unchanged original task/job/receipt. The historical fixture is inserted in its original shape; immutable history triggers remain enabled.
- Broader conversation intelligence/outbox/CI contract suites after the progress-generation regression additions: **1113 passed, 17 skipped**. The skips require a matching native build or POSIX ownership; they are not counted as successful execution.
- Ruff whole Python source/tests: passed. Mypy: **301 source files, no issues**.
- Production Next standalone build and dedicated CI wrapper contracts: passed locally. The complete compiled browser gate passed against disposable PostgreSQL with Node 24.19.0, one required test, 15 journey assertions, 76 HTTP receipts, no API interception, no page errors, and no provider network calls. Challenge, native transport, and provider adapters are explicitly synthetic. See `browser-local-receipt.json`, `browser-local-proof.json`, and the separate browser-gate evidence.
- Committed upload replay PostgreSQL/HTTP regression suite: **4 passed**; existing intake PostgreSQL suite: **9 passed**. The ready-recording negatives separately verify another valid session, retention expiry with otherwise-valid permission, permission expiry, revocation, deletion, and changed bytes.
- Independent read-only review of report adaptation and retained C5 revision/replay/locking found no P1 or P2 defects. Exact-release Linux CI and deployment remain pending at this checkpoint.

Test data is synthetic. No customer audio or provider response body is embedded here. Initial local runs failed because Windows user-profile scratch had a Git ancestor; rerunning in dedicated D-drive scratch outside repositories passed. The new upgrade fixture initially attempted an update rejected by the immutable-history trigger; it was replaced with insertion of the legacy shape, preserving that guard.

## Remaining release gates

Complete final retry/progress regression proofs and static checks; freeze and commit the candidate; require exact-source CI and artifacts; prepare coordinated staging activation; recover the retained staging call with the source-owned revalidation command; prove new guest/account real-provider journeys within existing approvals; then promote verified artifacts and run production canary. Human coaching quality review and a measured soak remain separate evidence.

## Exact-candidate findings and retained-call preflight

The first exact candidate, `66240141624a4526738cb0cde8eadee92f1ae160`, passed static, frontend, infrastructure gates, and the native image build, but application CI correctly blocked packaging. The dedicated browser job lacked an explicit FFmpeg prerequisite. Broader database tests also exposed that the coordinator must observe existing terminal tasks to preserve a specific C2 hold and execute its separately authorized bounded C5 repair. The public fresh-request fence remains in `inference.request_stage`; observing a terminal task in the coordinator does not redispatch it. An older PostgreSQL test that expected generic retry to erase ambiguous provider evidence is updated to require reconciliation and prove that the job cannot be claimed again.

The actual paused staging C5 response was read through the existing source-owned binding and Admin checks, with a SELECT-only query guard and transaction rollback. The local current validator admitted its exact retained bytes and original reconstructed request: a detailed overview, two strengths, two improvements, one missed opportunity, one objection finding, and one closing finding. `retained-local-validation-proof.json` records hashes and counts only. This preflight made zero provider calls and zero database writes; it is not yet a published recovered version or a deployed browser result. Private content remains outside Git.

## Live staging follow-up

`staging-live-verification.md` supersedes the pending staging status above. The
retained response was subsequently recovered with the source-owned CLI, and a
fresh synthetic guest upload completed the real C2/C4/C5 pipeline. Both report
endpoints returned valid reports; the deployed browser rejected supported
`recovery` envelope metadata and optional overview `business_impact`.

The follow-up accepts only these declared fields with strict subfield validation.
It preserves source/transcript/evidence bindings, unknown-field rejection, and
the prohibition on claiming official or human-approved scores. The normal
frontend parser now accepts the exact privately held recovered projection,
without removing any fields or making provider calls. Focused regressions
passed (41 tests), and the complete Sales Xray web suite passed (28 files,
271 tests). Independent review found no remaining P1/P2 findings in this patch.
The compiled browser regression covers the supported detailed overview and
recovery metadata through an explicitly synthetic server adapter; actual
retained-C5 CLI recovery is separately evidenced in staging.

Fresh provider self-metadata supersedes old token-expiry notes: active
ElevenLabs/Gemini service tokens are currently recognized and non-expiring.
The credential audit separately records their observed scope and maintenance
limitations; no new refresh service, credential, or permission was installed.
